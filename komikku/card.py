# Copyright (C) 2019-2021 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-only or GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from copy import deepcopy
from gettext import gettext as _
from gettext import ngettext as n_
import natsort
import time

from gi.repository import Adw
from gi.repository import Gdk
from gi.repository import Gio
from gi.repository import GLib
from gi.repository import GObject
from gi.repository import Gtk
from gi.repository.GdkPixbuf import Pixbuf

from komikku.models import create_db_connection
from komikku.models import Category
from komikku.models import Download
from komikku.models import Settings
from komikku.models import update_rows
from komikku.servers import get_file_mime_type
from komikku.utils import folder_size
from komikku.utils import html_escape
from komikku.utils import PaintablePixbufAnimation


class Card:
    manga = None
    selection_mode = False

    def __init__(self, window):
        self.window = window
        self.builder = window.builder
        self.builder.add_from_resource('/info/febvre/Komikku/ui/menu/card.xml')
        self.builder.add_from_resource('/info/febvre/Komikku/ui/menu/card_selection_mode.xml')

        self.viewswitchertitle = self.window.card_viewswitchertitle
        self.resume_read_button = self.window.card_resume_read_button

        self.stack = self.window.card_stack
        self.info_grid = InfoGrid(self)
        self.categories_list = CategoriesList(self)
        self.chapters_list = ChaptersList(self)

        self.viewswitchertitle.bind_property('title-visible', self.window.card_viewswitcherbar, 'reveal', GObject.BindingFlags.SYNC_CREATE)
        self.resume_read_button.connect('clicked', self.on_resume_read_button_clicked)
        self.stack.connect('notify::visible-child', self.on_page_changed)
        self.window.updater.connect('manga-updated', self.on_manga_updated)

    def add_actions(self):
        self.delete_action = Gio.SimpleAction.new('card.delete', None)
        self.delete_action.connect('activate', self.on_delete_menu_clicked)
        self.window.application.add_action(self.delete_action)

        self.update_action = Gio.SimpleAction.new('card.update', None)
        self.update_action.connect('activate', self.on_update_menu_clicked)
        self.window.application.add_action(self.update_action)

        self.sort_order_action = Gio.SimpleAction.new_stateful('card.sort-order', GLib.VariantType.new('s'), GLib.Variant('s', 'desc'))
        self.sort_order_action.connect('change-state', self.chapters_list.on_sort_order_changed)
        self.window.application.add_action(self.sort_order_action)

        open_in_browser_action = Gio.SimpleAction.new('card.open-in-browser', None)
        open_in_browser_action.connect('activate', self.on_open_in_browser_menu_clicked)
        self.window.application.add_action(open_in_browser_action)

        self.chapters_list.add_actions()

    def enter_selection_mode(self):
        self.selection_mode = True

        self.chapters_list.enter_selection_mode()

        self.window.headerbar.get_style_context().add_class('selection-mode')
        self.viewswitchertitle.set_view_switcher_enabled(False)
        self.window.menu_button.set_menu_model(self.builder.get_object('menu-card-selection-mode'))

    def init(self, manga, transition=True):
        # Default page is `Info` page except when we come from Explorer
        self.stack.set_visible_child_name('chapters' if self.window.page == 'explorer' else 'info')

        self.manga = manga
        # Unref chapters to force a reload
        self.manga._chapters = None

        if manga.server.status == 'disabled':
            self.window.show_notification(
                _('NOTICE\n{0} server is not longer supported.\nPlease switch to another server.').format(manga.server.name)
            )

        self.show(transition)

        self.populate()

    def leave_selection_mode(self, _param=None):
        self.selection_mode = False

        self.chapters_list.leave_selection_mode()

        self.window.headerbar.get_style_context().remove_class('selection-mode')
        self.viewswitchertitle.set_view_switcher_enabled(True)
        self.window.menu_button.set_menu_model(self.builder.get_object('menu-card'))

    def on_delete_menu_clicked(self, action, param):
        def confirm_callback():
            # Stop Downloader & Updater
            self.window.downloader.stop()
            self.window.updater.stop()

            while self.window.downloader.running or self.window.updater.running:
                time.sleep(0.1)
                continue

            # Safely delete manga in DB
            self.manga.delete()

            # Restart Downloader & Updater
            self.window.downloader.start()
            self.window.updater.start()

            # Finally, update and show library
            db_conn = create_db_connection()
            nb_mangas = db_conn.execute('SELECT count(*) FROM mangas').fetchone()[0]
            db_conn.close()

            if nb_mangas == 0:
                # Library is now empty
                self.window.library.populate()
            else:
                self.window.library.on_manga_deleted(self.manga)

            self.window.library.show()

        self.window.confirm(
            _('Delete?'),
            _('Are you sure you want to delete this manga?'),
            confirm_callback
        )

    def on_manga_updated(self, updater, manga, nb_recent_chapters, nb_deleted_chapters, synced):
        if self.window.page == 'card' and self.manga.id == manga.id:
            self.manga = manga

            if manga.server.sync:
                self.window.show_notification(_('Read progress synchronization with server completed successfully'))

            if nb_recent_chapters > 0 or nb_deleted_chapters > 0 or synced:
                self.chapters_list.populate()

            self.info_grid.populate()

    def on_open_in_browser_menu_clicked(self, action, param):
        if url := self.manga.server.get_manga_url(self.manga.slug, self.manga.url):
            Gtk.show_uri_on_window(None, url, time.time())
        else:
            self.window.show_notification(_('Failed to get manga URL'))

    def on_page_changed(self, _stack, _param):
        if self.selection_mode and self.stack.get_visible_child_name() != 'chapters':
            self.leave_selection_mode()

    def on_resume_read_button_clicked(self, widget):
        chapters = [child.chapter for child in self.chapters_list.listbox.get_children()]
        if self.chapters_list.sort_order.endswith('desc'):
            chapters.reverse()

        chapter = None
        for chapter_ in chapters:
            if not chapter_.read:
                chapter = chapter_
                break

        if not chapter:
            chapter = chapters[0]

        self.window.reader.init(self.manga, chapter)

    def on_update_menu_clicked(self, action, param):
        self.window.updater.add(self.manga)
        self.window.updater.start()

    def populate(self):
        self.chapters_list.set_sort_order(invalidate=False)
        self.chapters_list.populate()
        self.info_grid.populate()
        self.categories_list.populate()

    def set_actions_enabled(self, enabled):
        self.delete_action.set_enabled(enabled)
        self.update_action.set_enabled(enabled)
        self.sort_order_action.set_enabled(enabled)

    def show(self, transition=True):
        self.viewswitchertitle.set_title(self.manga.name)

        self.window.left_button.set_icon_name('go-previous-symbolic')
        self.window.library_flap_reveal_button.hide()
        self.window.right_button_stack.set_visible_child_name('card')

        self.window.menu_button.set_menu_model(self.builder.get_object('menu-card'))
        self.window.menu_button.set_icon_name('view-more-symbolic')
        self.window.menu_button.show()

        self.window.show_page('card', transition=transition)

    def stop_populate(self):
        # Allows to stop chapters list population when we leave card page
        # in case it's not completed (occurs with very long series)
        self.chapters_list.populate_generator_stop_flag = True

    def refresh(self, chapters):
        self.info_grid.refresh()
        self.chapters_list.refresh(chapters)


class CategoriesList:
    def __init__(self, card):
        self.card = card
        self.window = card.window

        self.stack = self.window.card_categories_stack
        self.listbox = self.window.card_categories_listbox
        self.listbox.get_style_context().add_class('list-bordered')

    def clear(self):
        row = self.listbox.get_first_child()
        while row:
            next_row = row.get_next_sibling()
            self.listbox.remove(row)
            row = next_row

    def populate(self):
        self.clear()

        db_conn = create_db_connection()
        records = db_conn.execute('SELECT * FROM categories ORDER BY label ASC').fetchall()
        db_conn.close()

        if records:
            self.stack.set_visible_child_name('list')

            for record in records:
                category = Category.get(record['id'])

                action_row = Adw.ActionRow()
                action_row.set_title(category.label)
                action_row.set_activatable(True)

                switch = Gtk.Switch.new()
                switch.set_valign(Gtk.Align.CENTER)
                switch.set_halign(Gtk.Align.CENTER)
                switch.set_active(category.id in self.card.manga.categories)
                switch.connect('notify::active', self.on_category_activated, category.id)
                action_row.add_suffix(switch)
                action_row.set_activatable_widget(switch)

                self.listbox.append(action_row)
        else:
            self.stack.set_visible_child_name('empty')

    def on_category_activated(self, switch, _param, category_id):
        self.card.manga.toggle_category(category_id, switch.get_active())

        # Update the categories list in Library, just in case it's necessary to show/hide the 'Uncategorized' category
        self.window.library.categories_list.populate()

        # Update Library if the current selected category is the activated category or the 'Uncategorized' category
        if Settings.get_default().selected_category in (-1, category_id):
            self.window.library.populate()


class ChaptersList:
    selection_mode_range = False
    selection_mode_last_row_index = None
    selection_mode_last_walk_direction = None
    populate_generator_stop_flag = False

    def __init__(self, card):
        self.card = card
        self.window = card.window

        self.listbox = self.window.card_chapters_listbox
        self.listbox.get_style_context().add_class('list-bordered')
        # self.listbox.connect('key-press-event', self.on_key_pressed)
        self.listbox.connect('row-activated', self.on_chapter_row_clicked)
        self.listbox.connect('selected-rows-changed', self.on_selection_changed)
        self.listbox.connect('unselect-all', self.card.leave_selection_mode)

        # self.gesture = Gtk.GestureLongPress.new(self.listbox)
        # self.gesture.set_touch_only(False)
        # self.gesture.connect('pressed', self.on_gesture_long_press_activated)

        self.window.downloader.connect('download-changed', self.update_chapter_row)

    @property
    def sort_order(self):
        return self.card.manga.sort_order or 'desc'

    def add_actions(self):
        # Menu actions in selection mode
        download_selected_chapters_action = Gio.SimpleAction.new('card.download-selected-chapters', None)
        download_selected_chapters_action.connect('activate', self.download_selected_chapters)
        self.window.application.add_action(download_selected_chapters_action)

        mark_selected_chapters_as_read_action = Gio.SimpleAction.new('card.mark-selected-chapters-read', None)
        mark_selected_chapters_as_read_action.connect('activate', self.toggle_selected_chapters_read_status, 1)
        self.window.application.add_action(mark_selected_chapters_as_read_action)

        mark_selected_chapters_as_unread_action = Gio.SimpleAction.new('card.mark-selected-chapters-unread', None)
        mark_selected_chapters_as_unread_action.connect('activate', self.toggle_selected_chapters_read_status, 0)
        self.window.application.add_action(mark_selected_chapters_as_unread_action)

        reset_selected_chapters_action = Gio.SimpleAction.new('card.reset-selected-chapters', None)
        reset_selected_chapters_action.connect('activate', self.reset_selected_chapters)
        self.window.application.add_action(reset_selected_chapters_action)

        select_all_chapters_action = Gio.SimpleAction.new('card.select-all-chapters', None)
        select_all_chapters_action.connect('activate', self.select_all)
        self.window.application.add_action(select_all_chapters_action)

        # Chapters menu actions
        download_chapter_action = Gio.SimpleAction.new('card.download-chapter', None)
        download_chapter_action.connect('activate', self.download_chapter)
        self.window.application.add_action(download_chapter_action)

        mark_chapter_as_read_action = Gio.SimpleAction.new('card.mark-chapter-read', None)
        mark_chapter_as_read_action.connect('activate', self.toggle_chapter_read_status, 1)
        self.window.application.add_action(mark_chapter_as_read_action)

        mark_chapter_as_unread_action = Gio.SimpleAction.new('card.mark-chapter-unread', None)
        mark_chapter_as_unread_action.connect('activate', self.toggle_chapter_read_status, 0)
        self.window.application.add_action(mark_chapter_as_unread_action)

        reset_chapter_action = Gio.SimpleAction.new('card.reset-chapter', None)
        reset_chapter_action.connect('activate', self.reset_chapter)
        self.window.application.add_action(reset_chapter_action)

    def clear(self):
        child = self.listbox.get_first_child()
        while child:
            next_child = child.get_next_sibling()
            self.listbox.remove(child)
            child = next_child

    def download_chapter(self, action, param):
        # Add chapter in download queue
        self.window.downloader.add([self.action_row.chapter, ], emit_signal=True)
        self.window.downloader.start()

    def download_selected_chapters(self, action, param):
        # Add selected chapters in download queue
        self.window.downloader.add([row.chapter for row in self.listbox.get_selected_rows()], emit_signal=True)
        self.window.downloader.start()

        self.card.leave_selection_mode()

    def enter_selection_mode(self):
        self.selection_mode_last_row_index = None
        self.selection_mode_last_walk_direction = None

        self.listbox.set_selection_mode(Gtk.SelectionMode.MULTIPLE)

    def leave_selection_mode(self):
        self.listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        for row in self.listbox.get_children():
            row._selected = False

    def on_chapter_row_button_pressed(self, event_box, event):
        row = event_box.get_parent()
        if not self.card.selection_mode and event.type == Gdk.EventType.BUTTON_PRESS and event.button == 3 and row is not None:
            self.card.enter_selection_mode()
            self.on_chapter_row_clicked(None, row)
            return Gdk.EVENT_STOP

        return Gdk.EVENT_PROPAGATE

    def on_chapter_row_clicked(self, _listbox, row):
        state = self.window.controller_key.get_current_event_state()
        modifiers = Gtk.accelerator_get_default_mod_mask()

        # Enter selection mode if <Control>+Click or <Shift>+Click is done
        if state & modifiers in (Gdk.ModifierType.CONTROL_MASK, Gdk.ModifierType.SHIFT_MASK) and not self.card.selection_mode:
            self.card.enter_selection_mode()

        if self.card.selection_mode:
            if state & modifiers == Gdk.ModifierType.SHIFT_MASK:
                # Enter range selection mode if <Shift>+Click is done
                self.selection_mode_range = True
            if self.selection_mode_range and self.selection_mode_last_row_index is not None:
                # Range selection mode: select all rows between last selected row and clicked row
                walk_index = self.selection_mode_last_row_index
                last_index = row.get_index()

                while walk_index != last_index:
                    walk_row = self.listbox.get_row_at_index(walk_index)
                    if walk_row and not walk_row._selected:
                        self.listbox.select_row(walk_row)
                        walk_row._selected = True

                    if walk_index < last_index:
                        walk_index += 1
                    else:
                        walk_index -= 1

            self.selection_mode_range = False

            if row._selected:
                self.listbox.unselect_row(row)
                self.selection_mode_last_row_index = None
                row._selected = False
            else:
                self.listbox.select_row(row)
                self.selection_mode_last_row_index = row.get_index()
                row._selected = True

            if len(self.listbox.get_selected_rows()) == 0:
                self.card.leave_selection_mode()
        else:
            self.window.reader.init(self.card.manga, row.chapter)

    def on_gesture_long_press_activated(self, gesture, x, y):
        if self.card.selection_mode:
            # Enter in 'Range' selection mode
            # Long press on a chapter row then long press on another to select everything in between
            self.selection_mode_range = True
        else:
            self.card.enter_selection_mode()

    def on_key_pressed(self, _widget, event):
        if event.keyval not in (Gdk.KEY_Up, Gdk.KEY_KP_Up, Gdk.KEY_Down, Gdk.KEY_KP_Down) or not self.card.selection_mode:
            return Gdk.EVENT_STOP

        modifiers = Gtk.accelerator_get_default_mod_mask()
        is_single = event.state & modifiers != Gdk.ModifierType.SHIFT_MASK
        walk_index = self.selection_mode_last_row_index
        walk_row = None

        if event.keyval in (Gdk.KEY_Up, Gdk.KEY_KP_Up):
            walk_direction = -1
        elif event.keyval in (Gdk.KEY_Down, Gdk.KEY_KP_Down):
            walk_direction = 1

        # Determine the row to select
        if is_single or self.selection_mode_last_walk_direction in (None, walk_direction):
            walk_index += walk_direction
        self.selection_mode_last_walk_direction = walk_direction

        walk_row = self.listbox.get_row_at_index(walk_index)
        if walk_row:
            self.selection_mode_last_row_index = walk_index
        elif is_single:
            # Out of bounds, but since we only mark that row it's fine
            # also we might be changing from multi to single row selection and needed to unselect previously selected rows
            walk_row = self.listbox.get_row_at_index(self.selection_mode_last_row_index)
        else:
            return Gdk.EVENT_STOP

        # Actual selection
        if is_single:
            self.listbox.select_row(walk_row)
            walk_row._selected = True

            # Unselect previously selected rows in multi selection (with SHIFT modifier)
            for row in self.listbox.get_selected_rows():
                if row is not walk_row:
                    self.listbox.unselect_row(row)
                    row._selected = False

            self.selection_mode_last_walk_direction = None
        elif walk_row._selected:
            self.listbox.unselect_row(walk_row)
            walk_row._selected = False
        else:
            self.listbox.select_row(walk_row)
            walk_row._selected = True

        return Gdk.EVENT_STOP

    def on_selection_changed(self, _flowbox):
        number = len(self.listbox.get_selected_rows())
        if number:
            self.card.viewswitchertitle.set_subtitle(n_('{0} selected', '{0} selected', number).format(number))
        else:
            self.card.viewswitchertitle.set_subtitle('')

    def on_sort_order_changed(self, action, variant):
        value = variant.get_string()
        if value == self.card.manga.sort_order:
            return

        self.card.manga.update(dict(sort_order=value))
        self.set_sort_order()

    def populate(self):
        self.clear()

        self.card.resume_read_button.set_sensitive(False)

        if not self.card.manga.chapters:
            return

        def add_chapters_rows():
            for chapter in self.card.manga.chapters:
                if self.populate_generator_stop_flag:
                    self.window.activity_indicator.stop()
                    return

                row = Gtk.ListBoxRow()
                row.get_style_context().add_class('card-chapter-listboxrow')
                row.chapter = chapter
                row.download = None
                row._selected = False
                self.populate_chapter_row(row)
                self.listbox.append(row)
                yield True

            self.listbox.set_sort_func(self.sort_func)
            self.listbox.invalidate_sort()
            self.card.set_actions_enabled(True)
            self.card.resume_read_button.set_sensitive(True)
            self.window.activity_indicator.stop()

        def run_generator(func):
            self.window.activity_indicator.start()
            self.card.set_actions_enabled(False)

            gen = func()
            GLib.idle_add(lambda: next(gen, False), priority=GLib.PRIORITY_DEFAULT_IDLE)

        self.populate_generator_stop_flag = False
        self.listbox.set_sort_func(None)

        run_generator(add_chapters_rows)

    def populate_chapter_row(self, row):
        # event_box = Gtk.EventBox.new()
        # event_box.connect('button-press-event', self.on_chapter_row_button_pressed)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        # event_box.add(box)
        # row.add(event_box)
        row.set_child(box)

        chapter = row.chapter

        #
        # Title, scanlators, action button
        #
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)

        # Title
        label = Gtk.Label(xalign=0, hexpand=True)
        label.set_valign(Gtk.Align.CENTER)
        ctx = label.get_style_context()
        ctx.add_class('card-chapter-label')
        if chapter.read:
            # Chapter reading ended
            ctx.add_class('dim-label')
        elif chapter.last_page_read_index is not None:
            # Chapter reading started
            ctx.add_class('card-chapter-label-started')
        label.set_wrap(True)
        title = chapter.title
        if self.card.manga.name != title and self.card.manga.name in title:
            title = title.replace(self.card.manga.name, '').strip()
        label.set_markup(html_escape(title))

        if chapter.scanlators:
            # Vertical box for title and scanlators
            vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, hexpand=True)

            # Add title
            vbox.append(label)

            # Scanlators
            label = Gtk.Label(xalign=0)
            label.set_valign(Gtk.Align.CENTER)
            ctx = label.get_style_context()
            ctx.add_class('dim-label')
            ctx.add_class('card-chapter-sublabel')
            label.set_wrap(True)
            label.set_markup(html_escape(', '.join(chapter.scanlators)))
            vbox.append(label)

            hbox.append(vbox)
        else:
            # Title only
            hbox.append(label)

        # Action button
        button = Gtk.MenuButton.new()
        button.set_icon_name('view-more-symbolic')
        button.props.has_frame = False
        popover = Gtk.PopoverMenu(margin_start=6, margin_end=6, margin_top=6, margin_bottom=6)
        popover.connect('show', self.show_chapter_menu, row)
        button.set_popover(popover)

        hbox.append(button)

        box.append(hbox)

        #
        # Recent badge, date, download status, page counter
        #
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)

        # Recent badge
        if chapter.recent == 1:
            label = Gtk.Label(xalign=0, yalign=1)
            label.set_valign(Gtk.Align.CENTER)
            ctx = label.get_style_context()
            ctx.add_class('card-chapter-sublabel')
            ctx.add_class('badge')
            label.set_text(_('New'))
            hbox.append(label)

        # Date + Download status (text or progress bar)
        download_status = None
        if chapter.downloaded:
            download_status = 'downloaded'
        else:
            if row.download is None:
                row.download = Download.get_by_chapter_id(chapter.id)
            if row.download:
                download_status = row.download.status

        label = Gtk.Label(xalign=0, yalign=1, hexpand=True)
        label.set_valign(Gtk.Align.CENTER)
        label.get_style_context().add_class('card-chapter-sublabel')
        text = chapter.date.strftime(_('%m/%d/%Y')) if chapter.date else ''
        if download_status is not None and download_status != 'downloading':
            text = f'{text} - {_(Download.STATUSES[download_status]).upper()}'
        label.set_text(text)

        if download_status == 'downloading':
            hbox.append(label)

            # Download progress
            progressbar = Gtk.ProgressBar()
            progressbar.set_valign(Gtk.Align.CENTER)
            progressbar.set_fraction(row.download.percent / 100)
            hbox.append(progressbar)

            stop_button = Gtk.Button.new_from_icon_name('media-playback-stop-symbolic')
            stop_button.connect('clicked', lambda button, chapter: self.window.downloader.remove(chapter), chapter)
            hbox.append(stop_button)
        else:
            hbox.append(label)

            # Counter: nb read / nb pages
            if not chapter.read:
                label = Gtk.Label(xalign=0.5, yalign=1)
                label.set_valign(Gtk.Align.CENTER)
                label.get_style_context().add_class('card-chapter-sublabel')
                if chapter.last_page_read_index is not None:
                    nb_pages = len(chapter.pages) if chapter.pages else '?'
                    label.set_text(f'{chapter.last_page_read_index + 1}/{nb_pages}')
                hbox.append(label)

        box.append(hbox)

    def refresh(self, chapters):
        for chapter in chapters:
            self.update_chapter_row(chapter=chapter)

    def reset_chapter(self, action, param):
        chapter = self.action_row.chapter

        chapter.reset()

        self.populate_chapter_row(self.action_row)

    def reset_selected_chapters(self, action, param):
        for row in self.listbox.get_selected_rows():
            chapter = row.chapter

            chapter.reset()

            self.populate_chapter_row(row)

        self.card.leave_selection_mode()

    def select_all(self, action=None, param=None):
        if self.card.stack.get_visible_child_name() != 'chapters':
            return

        if not self.card.selection_mode:
            self.card.enter_selection_mode()

        def select_chapters_rows():
            for row in self.listbox.get_children():
                if row._selected:
                    continue

                self.listbox.select_row(row)
                row._selected = True
                yield True

            self.window.activity_indicator.stop()
            self.window.menu_button.set_sensitive(True)

        def run_generator(func):
            self.window.activity_indicator.start()
            self.window.menu_button.set_sensitive(False)

            gen = func()
            GLib.idle_add(lambda: next(gen, False), priority=GLib.PRIORITY_DEFAULT_IDLE)

        run_generator(select_chapters_rows)

    def set_sort_order(self, invalidate=True):
        self.card.sort_order_action.set_state(GLib.Variant('s', self.sort_order))
        if invalidate:
            self.listbox.invalidate_sort()

    def show_chapter_menu(self, popover, row):
        chapter = row.chapter
        self.action_row = row

        menu = Gio.Menu()
        if chapter.pages:
            menu.append(_('Reset'), 'app.card.reset-chapter')
        if not chapter.downloaded:
            menu.append(_('Download'), 'app.card.download-chapter')
        if not chapter.read:
            menu.append(_('Mark as Read'), 'app.card.mark-chapter-read')
        if chapter.read or chapter.last_page_read_index is not None:
            menu.append(_('Mark as Unread'), 'app.card.mark-chapter-unread')

        popover.set_menu_model(menu)

    def sort_func(self, child1, child2):
        """
        This function gets two children and has to return:
        - a negative integer if the firstone should come before the second one
        - zero if they are equal
        - a positive integer if the second one should come before the firstone
        """
        if self.sort_order in ('asc', 'desc'):
            if child1.chapter.rank > child2.chapter.rank:
                return -1 if self.sort_order == 'desc' else 1

            if child1.chapter.rank < child2.chapter.rank:
                return 1 if self.sort_order == 'desc' else -1

        elif self.sort_order in ('date-asc', 'date-desc') and child1.chapter.date and child2.chapter.date:
            if child1.chapter.date > child2.chapter.date and child1.chapter.id > child2.chapter.id:
                return -1 if self.sort_order == 'date-desc' else 1

            if child1.chapter.date < child2.chapter.date and child1.chapter.id < child2.chapter.id:
                return 1 if self.sort_order == 'date-desc' else -1

        elif self.sort_order in ('natural-asc', 'natural-desc'):
            l = natsort.natsorted([child1.chapter.title, child2.chapter.title], alg=natsort.ns.INT | natsort.ns.IC)
            if l[0] == child1.chapter.title:
                return 1 if self.sort_order == 'natural-desc' else -1

            return -1 if self.sort_order == 'natural-desc' else 1

        return 0

    def toggle_selected_chapters_read_status(self, action, param, read):
        chapters_ids = []
        chapters_data = []

        self.window.activity_indicator.start()

        # First, update DB
        for row in self.listbox.get_selected_rows():
            chapter = row.chapter

            if chapter.pages:
                pages = deepcopy(chapter.pages)
                for page in pages:
                    page['read'] = read
            else:
                pages = None

            chapters_ids.append(chapter.id)
            chapters_data.append(dict(
                last_page_read_index=None,
                pages=pages,
                read=read,
                recent=False,
            ))

        db_conn = create_db_connection()

        with db_conn:
            res = update_rows(db_conn, 'chapters', chapters_ids, chapters_data)

        db_conn.close()

        if res:
            # Then, if DB update succeeded, update chapters rows
            def update_chapters_rows():
                for row in self.listbox.get_selected_rows():
                    chapter = row.chapter

                    if chapter.pages:
                        for chapter_page in chapter.pages:
                            chapter_page['read'] = read

                    chapter.last_page_read_index = None
                    chapter.read = read
                    chapter.recent = False

                    self.populate_chapter_row(row)
                    yield True

                self.card.leave_selection_mode()
                self.window.activity_indicator.stop()

            def run_generator(func):
                gen = func()
                GLib.idle_add(lambda: next(gen, False), priority=GLib.PRIORITY_DEFAULT_IDLE)

            run_generator(update_chapters_rows)
        else:
            self.window.activity_indicator.stop()
            self.card.leave_selection_mode()

    def toggle_chapter_read_status(self, action, param, read):
        chapter = self.action_row.chapter

        if chapter.pages:
            for chapter_page in chapter.pages:
                chapter_page['read'] = read

        data = dict(
            last_page_read_index=None,
            pages=chapter.pages,
            read=read,
            recent=False,
        )

        if chapter.update(data):
            self.populate_chapter_row(self.action_row)

    def update_chapter_row(self, downloader=None, download=None, chapter=None):
        """
        Update a specific chapter row
        - used when download status change (via signal from Downloader)
        - used when we come back from reader to update last page read
        """
        if chapter is None:
            chapter = download.chapter

        if self.card.window.page not in ('card', 'reader') or self.card.manga.id != chapter.manga_id:
            return

        row = self.listbox.get_first_child()
        while row:
            if row.chapter.id == chapter.id:
                row.chapter = chapter
                row.download = download
                self.populate_chapter_row(row)
                break
            row = row.get_next_sibling()


class InfoGrid:
    def __init__(self, card):
        self.card = card
        self.window = card.window

        self.window.card_info_box.get_style_context().add_class('card-info-box')
        self.window.card_info_box.get_style_context().add_class('list-bordered')

        self.name_label = self.window.card_name_label
        self.cover_image = self.window.card_cover_image
        self.authors_value_label = self.window.card_authors_value_label
        self.genres_value_label = self.window.card_genres_value_label
        self.status_value_label = self.window.card_status_value_label
        self.scanlators_value_label = self.window.card_scanlators_value_label
        self.server_value_label = self.window.card_server_value_label
        self.last_update_value_label = self.window.card_last_update_value_label
        self.synopsis_value_label = self.window.card_synopsis_value_label
        self.more_label = self.window.card_more_label

    def populate(self):
        cover_width = 170
        manga = self.card.manga

        self.name_label.set_text(manga.name)

        if manga.cover_fs_path is None:
            pixbuf = Pixbuf.new_from_resource_at_scale('/info/febvre/Komikku/images/missing_file.png', cover_width, -1, True)
        else:
            try:
                if get_file_mime_type(manga.cover_fs_path) != 'image/gif':
                    pixbuf = Pixbuf.new_from_file_at_scale(manga.cover_fs_path, cover_width, -1, True)
                else:
                    pixbuf = PaintablePixbufAnimation(manga.cover_fs_path)
            except Exception:
                # Invalid image, corrupted image, unsupported image format,...
                pixbuf = Pixbuf.new_from_resource_at_scale('/info/febvre/Komikku/images/missing_file.png', cover_width, -1, True)

        self.cover_image.clear()
        if isinstance(pixbuf, Gdk.Paintable):
            self.cover_image.set_from_paintable(pixbuf)
        else:
            self.cover_image.set_from_pixbuf(pixbuf)

        authors = html_escape(', '.join(manga.authors)) if manga.authors else '-'
        self.authors_value_label.set_markup('<span size="small">{0}</span>'.format(authors))

        genres = html_escape(', '.join(manga.genres)) if manga.genres else '-'
        self.genres_value_label.set_markup('<span size="small">{0}</span>'.format(genres))

        status = _(manga.STATUSES[manga.status]) if manga.status else '-'
        self.status_value_label.set_markup('<span size="small">{0}</span>'.format(status))

        scanlators = html_escape(', '.join(manga.scanlators)) if manga.scanlators else '-'
        self.scanlators_value_label.set_markup('<span size="small">{0}</span>'.format(scanlators))

        self.server_value_label.set_markup(
            '<span size="small">{0} [{1}] - {2} chapters</span>'.format(
                html_escape(manga.server.name), manga.server.lang.upper(), len(manga.chapters)
            )
        )

        self.last_update_value_label.set_markup(
            '<span size="small">{0}</span>'.format(manga.last_update.strftime('%m/%d/%Y')) if manga.last_update else '-')

        self.synopsis_value_label.set_text(manga.synopsis or '-')

        self.set_disk_usage()

    def refresh(self):
        self.set_disk_usage()

    def set_disk_usage(self):
        self.more_label.set_markup('<i>{0}</i>'.format(_('Disk space used: {0}').format(folder_size(self.card.manga.path))))
