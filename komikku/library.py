# Copyright (C) 2019-2021 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-only or GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from copy import deepcopy
from gettext import gettext as _
from gettext import ngettext as n_
import math
import threading
import time

from gi.repository import Adw
from gi.repository import Gdk
from gi.repository import Gio
from gi.repository import GLib
from gi.repository import GObject
from gi.repository import Gtk
from gi.repository.GdkPixbuf import InterpType
from gi.repository.GdkPixbuf import Pixbuf
from gi.repository.GdkPixbuf import PixbufAnimation

from komikku.models import Category
from komikku.models import create_db_connection
from komikku.models import delete_rows
from komikku.models import insert_rows
from komikku.models import Manga
from komikku.models import Settings
from komikku.models import update_rows
from komikku.servers import get_file_mime_type
from komikku.utils import create_cairo_surface_from_pixbuf
from komikku.utils import scale_pixbuf_animation


class Library:
    page = None
    search_menu_filters = {}
    selection_mode = False
    selection_mode_range = False
    selection_mode_last_thumbnail_index = None
    thumbnails_size = None

    def __init__(self, window):
        self.window = window
        self.builder = window.builder
        self.builder.add_from_resource('/info/febvre/Komikku/ui/menu/library_search.xml')
        self.builder.add_from_resource('/info/febvre/Komikku/ui/menu/library_selection_mode.xml')

        self.subtitle_label = self.window.library_subtitle_label
        self.stack = self.window.library_stack

        # Search
        self.searchbar = self.window.library_searchbar
        self.search_menu_button = self.window.library_search_menu_button
        self.search_menu_button.set_menu_model(self.builder.get_object('menu-library-search'))
        self.search_entry = self.window.library_searchentry
        self.search_entry.connect('activate', self.on_search_entry_activated)
        self.search_entry.connect('changed', self.search)
        self.search_button = self.window.library_search_button
        self.searchbar.bind_property(
            'search-mode-enabled', self.search_button, 'active', GObject.BindingFlags.BIDIRECTIONAL | GObject.BindingFlags.SYNC_CREATE
        )
        self.searchbar.connect_entry(self.search_entry)
        self.searchbar.set_key_capture_widget(self.window)

        # Flap (categories)
        self.flap = self.window.library_flap
        self.flap.props.transition_type = Adw.FlapTransitionType.OVER
        self.flap.props.fold_policy = Adw.FlapFoldPolicy.ALWAYS
        self.flap.props.modal = True
        self.flap.props.swipe_to_close = True
        self.flap.props.swipe_to_open = True
        self.flap.connect('notify::reveal-flap', self.on_flap_revealed)
        self.flap_reveal_button = self.window.library_flap_reveal_button
        self.flap_reveal_button_toggled_handler_id = self.flap_reveal_button.connect('toggled', self.toggle_flap)

        self.categories_list = CategoriesList(self)
        self.categories_list.populate()

        # Mangas Flowbox
        self.flowbox = self.window.library_flowbox
        self.flowbox.set_valign(Gtk.Align.START)
        self.flowbox.connect('child-activated', self.on_manga_clicked)
        self.flowbox.connect('selected-children-changed', self.update_subtitle)
        self.flowbox.connect('unselect-all', self.leave_selection_mode)

        self.gesture_click = Gtk.GestureClick.new()
        self.gesture_click.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        self.gesture_click.set_button(3)
        self.gesture_click.connect('released', self.on_right_click)
        self.flowbox.add_controller(self.gesture_click)

        # self.gesture = Gtk.GestureLongPress.new(self.flowbox)
        # self.gesture.set_touch_only(False)
        # self.gesture.connect('pressed', self.on_gesture_long_press_activated)

        self.window.updater.connect('manga-updated', self.on_manga_updated)

        def _filter(thumbnail):
            manga = thumbnail.manga
            term = self.search_entry.get_text().lower()

            # Search in name
            ret = term in manga.name.lower()

            # Search in server name
            ret = ret or term in manga.server.name.lower()

            # Search in genres (exact match)
            ret = ret or term in [genre.lower() for genre in manga.genres]

            # Optional menu filters
            if ret and self.search_menu_filters.get('downloaded'):
                ret = manga.nb_downloaded_chapters > 0
            if ret and self.search_menu_filters.get('unread'):
                ret = manga.nb_unread_chapters > 0
            if ret and self.search_menu_filters.get('recents'):
                ret = manga.nb_recent_chapters > 0

            if not ret and thumbnail._selected:
                # Unselect thumbnail if it's selected
                self.flowbox.unselect_child(thumbnail)
                thumbnail._selected = False

            thumbnail._filtered = not ret

            return ret

        def _sort(thumbnail1, thumbnail2):
            """
            This function gets two children and has to return:
            - a negative integer if the firstone should come before the second one
            - zero if they are equal
            - a positive integer if the second one should come before the firstone
            """
            manga1 = thumbnail1.manga
            manga2 = thumbnail2.manga

            if manga1.last_read > manga2.last_read:
                return -1

            if manga1.last_read < manga2.last_read:
                return 1

            return 0

        self.populate()

        self.flowbox.set_filter_func(_filter)
        self.flowbox.set_sort_func(_sort)

    def add_actions(self):
        # Menu actions
        update_action = Gio.SimpleAction.new('library.update', None)
        update_action.connect('activate', self.update_all)
        self.window.application.add_action(update_action)

        download_manager_action = Gio.SimpleAction.new('library.download-manager', None)
        download_manager_action.connect('activate', self.open_download_manager)
        self.window.application.add_action(download_manager_action)

        categories_editor_action = Gio.SimpleAction.new('library.categories-editor', None)
        categories_editor_action.connect('activate', self.open_categories_editor)
        self.window.application.add_action(categories_editor_action)

        # Search menu actions
        search_downloaded_action = Gio.SimpleAction.new_stateful('library.search.downloaded', None, GLib.Variant('b', False))
        search_downloaded_action.connect('change-state', self.on_search_menu_action_changed)
        self.window.application.add_action(search_downloaded_action)

        search_unread_action = Gio.SimpleAction.new_stateful('library.search.unread', None, GLib.Variant('b', False))
        search_unread_action.connect('change-state', self.on_search_menu_action_changed)
        self.window.application.add_action(search_unread_action)

        search_recents_action = Gio.SimpleAction.new_stateful('library.search.recents', None, GLib.Variant('b', False))
        search_recents_action.connect('change-state', self.on_search_menu_action_changed)
        self.window.application.add_action(search_recents_action)

        # Menu actions in selection mode
        update_selected_action = Gio.SimpleAction.new('library.update-selected', None)
        update_selected_action.connect('activate', self.update_selected)
        self.window.application.add_action(update_selected_action)

        delete_selected_action = Gio.SimpleAction.new('library.delete-selected', None)
        delete_selected_action.connect('activate', self.delete_selected)
        self.window.application.add_action(delete_selected_action)

        download_selected_action = Gio.SimpleAction.new('library.download-selected', None)
        download_selected_action.connect('activate', self.download_selected)
        self.window.application.add_action(download_selected_action)

        mark_selected_read_action = Gio.SimpleAction.new('library.mark-selected-read', None)
        mark_selected_read_action.connect('activate', self.toggle_selected_read_status, 1)
        self.window.application.add_action(mark_selected_read_action)

        mark_selected_unread_action = Gio.SimpleAction.new('library.mark-selected-unread', None)
        mark_selected_unread_action.connect('activate', self.toggle_selected_read_status, 0)
        self.window.application.add_action(mark_selected_unread_action)

        edit_categories_selected_action = Gio.SimpleAction.new('library.edit-categories-selected', None)
        edit_categories_selected_action.connect('activate', self.edit_categories_selected)
        self.window.application.add_action(edit_categories_selected_action)

        select_all_action = Gio.SimpleAction.new('library.select-all', None)
        select_all_action.connect('activate', self.select_all)
        self.window.application.add_action(select_all_action)

    def add_manga(self, manga, position=-1):
        thumbnail = Thumbnail(self, manga, *self.thumbnails_size)
        self.flowbox.insert(thumbnail, position)

    def compute_thumbnails_size(self):
        default_width = 180
        default_height = 250

        container_width = self.window.get_size(Gtk.Orientation.HORIZONTAL)
        if not container_width:
            container_width = self.window.measure(Gtk.Orientation.HORIZONTAL, -1)[0]

        padding = 6  # flowbox children padding is set via CSS
        child_width = default_width + padding * 2
        nb = container_width // child_width + 1
        width = container_width // nb - (padding * 2)
        height = default_height // (default_width / width)

        self.thumbnails_size = (width, height, nb)

    def delete_selected(self, _action, _param):
        def confirm_callback():
            # Stop Downloader & Updater
            self.window.downloader.stop()
            self.window.updater.stop()

            while self.window.downloader.running or self.window.updater.running:
                time.sleep(0.1)
                continue

            # Safely delete mangas in DB
            for thumbnail in self.flowbox.get_selected_children():
                thumbnail.manga.delete()

            # Restart Downloader & Updater
            self.window.downloader.start()
            self.window.updater.start()

            # Finally, update library
            self.populate()

            self.leave_selection_mode()

        self.window.confirm(
            _('Delete?'),
            _('Are you sure you want to delete selected mangas?'),
            confirm_callback
        )

    def download_selected(self, _action, _param):
        chapters = []
        for thumbnail in self.flowbox.get_selected_children():
            for chapter in thumbnail.manga.chapters:
                chapters.append(chapter)

        self.leave_selection_mode()

        self.window.downloader.add(chapters)
        self.window.downloader.start()

    def edit_categories_selected(self, _action, _param):
        # Edit categories of selected mangas
        self.categories_list.enter_edit_mode()

    def enter_selection_mode(self, x=None, y=None, selected_thumbnail=None):
        # Hide search button: disable search
        self.window.right_button_stack.hide()

        self.selection_mode = True

        self.flowbox.set_selection_mode(Gtk.SelectionMode.MULTIPLE)

        if selected_thumbnail is None:
            if x is not None and y is not None:
                selected_thumbnail = self.flowbox.get_child_at_pos(x, y)
            else:
                selected_thumbnail = self.flowbox.get_child_at_index(0)

        self.flowbox.select_child(selected_thumbnail)
        selected_thumbnail._selected = True
        self.selection_mode_last_thumbnail_index = selected_thumbnail.get_index()

        self.window.headerbar.get_style_context().add_class('selection-mode')
        self.window.left_button.set_icon_name('go-previous-symbolic')
        self.window.menu_button.set_menu_model(self.builder.get_object('menu-library-selection-mode'))

    def leave_selection_mode(self, param=None):
        self.selection_mode = False

        if self.page == 'flowbox':
            # Show search button: re-enable search
            self.window.right_button_stack.show()

        self.flowbox.set_selection_mode(Gtk.SelectionMode.NONE)
        thumbnail = self.flowbox.get_first_child()
        while thumbnail:
            thumbnail._selected = False
            thumbnail = thumbnail.get_next_sibling()

        if self.categories_list.edit_mode:
            refresh_library = param == 'refresh_library'
            self.categories_list.leave_edit_mode(refresh_library=refresh_library)

        self.window.headerbar.get_style_context().remove_class('selection-mode')
        self.window.left_button.set_icon_name('list-add-symbolic')
        self.window.menu_button.set_menu_model(self.builder.get_object('menu'))

    def on_flap_revealed(self, _flap, _param):
        with self.flap_reveal_button.handler_block(self.flap_reveal_button_toggled_handler_id):
            self.flap_reveal_button.props.active = self.flap.get_reveal_flap()

        if self.categories_list.edit_mode and not self.flap.get_reveal_flap():
            self.categories_list.leave_edit_mode()

    def on_gesture_long_press_activated(self, _gesture, x, y):
        if self.selection_mode:
            # Enter in 'Range' selection mode
            # Long press on a manga then long press on another to select everything in between
            self.selection_mode_range = True

            selected_thumbnail = self.flowbox.get_child_at_pos(x, y)
            self.flowbox.select_child(selected_thumbnail)
            self.on_manga_clicked(self.flowbox, selected_thumbnail)
        else:
            self.enter_selection_mode(x, y)

    def on_manga_added(self, manga):
        """Called from 'Add dialog' when user clicks on [+] button"""
        db_conn = create_db_connection()
        nb_mangas = db_conn.execute('SELECT count(*) FROM mangas').fetchone()[0]
        db_conn.close()

        if nb_mangas == 1:
            # Library was previously empty
            self.populate()
        else:
            self.add_manga(manga, position=0)

    def on_manga_clicked(self, _flowbox, thumbnail):
        state = self.window.controller_key.get_current_event_state()
        modifiers = state & Gtk.accelerator_get_default_mod_mask()

        # Enter selection mode if <Control>+Click or <Shift>+Click is done
        if modifiers in (Gdk.ModifierType.CONTROL_MASK, Gdk.ModifierType.SHIFT_MASK) and not self.selection_mode:
            self.enter_selection_mode(selected_thumbnail=thumbnail)
            return Gdk.EVENT_PROPAGATE

        if self.selection_mode:
            if modifiers == Gdk.ModifierType.SHIFT_MASK:
                # Enter range selection mode if <Shift>+Click is done
                self.selection_mode_range = True
            if self.selection_mode_range and self.selection_mode_last_thumbnail_index is not None:
                # Range selection mode: select all mangas between last selected manga and clicked manga
                walk_index = self.selection_mode_last_thumbnail_index
                last_index = thumbnail.get_index()

                while walk_index != last_index:
                    walk_thumbnail = self.flowbox.get_child_at_index(walk_index)
                    if walk_thumbnail and not walk_thumbnail._selected:
                        self.flowbox.select_child(walk_thumbnail)
                        walk_thumbnail._selected = True

                    if walk_index < last_index:
                        walk_index += 1
                    else:
                        walk_index -= 1

            self.selection_mode_range = False

            if thumbnail._selected:
                self.selection_mode_last_thumbnail_index = None
                self.flowbox.unselect_child(thumbnail)
                thumbnail._selected = False
            else:
                self.selection_mode_last_thumbnail_index = thumbnail.get_index()
                thumbnail._selected = True

            if len(self.flowbox.get_selected_children()) == 0:
                self.leave_selection_mode()
        else:
            self.window.card.init(thumbnail.manga)

    def on_manga_deleted(self, manga):
        # Remove manga thumbnail in flowbox
        thumbnail = self.flowbox.get_first_child()
        while thumbnail:
            if thumbnail.manga.id == manga.id:
                self.flowbox.remove(thumbnail)
                break
            thumbnail = thumbnail.get_next_sibling()

    def on_manga_updated(self, _updater, manga, _nb_recent_chapters, _nb_deleted_chapters, _synced):
        for thumbnail in self.flowbox.get_children():
            if thumbnail.manga.id != manga.id:
                continue

            thumbnail.update(manga)
            break

    def on_right_click(self, _gesture, _n_press, x, y):
        thumbnail = self.flowbox.get_child_at_pos(x, y)
        if not self.selection_mode and thumbnail is not None:
            self.enter_selection_mode(selected_thumbnail=thumbnail)
            return Gdk.EVENT_STOP

        return Gdk.EVENT_PROPAGATE

    def on_search_entry_activated(self, _entry):
        """Open first manga in search when <Enter> is pressed"""
        thumbnail = self.flowbox.get_child_at_pos(0, 0)
        if thumbnail:
            self.on_manga_clicked(self.flowbox, thumbnail)

    def on_search_menu_action_changed(self, action, variant):
        value = variant.get_boolean()
        action.set_state(GLib.Variant('b', value))

        self.search_menu_filters[action.props.name.split('.')[-1]] = value
        if sum(self.search_menu_filters.values()):
            self.search_menu_button.get_style_context().add_class('button-warning')
        else:
            self.search_menu_button.get_style_context().remove_class('button-warning')

        self.flowbox.invalidate_filter()

    def on_resize(self):
        self.compute_thumbnails_size()

        if self.page == 'start_page':
            return

        self.flowbox.set_min_children_per_line(self.thumbnails_size[2])
        thumbnail = self.flowbox.get_first_child()
        while thumbnail:
            thumbnail.resize(*self.thumbnails_size[:2])
            thumbnail = thumbnail.get_next_sibling()

    def open_categories_editor(self, action, param):
        self.window.categories_editor.show()

    def open_download_manager(self, action, param):
        self.window.download_manager.show()

    def populate(self):
        db_conn = create_db_connection()

        self.update_subtitle(db_conn=db_conn)

        selected_category_id = Settings.get_default().selected_category
        if selected_category_id > 0:
            # A true (from DB) category is selected
            mangas_rows = db_conn.execute(
                'SELECT m.id FROM categories_mangas_association cma JOIN mangas m ON cma.manga_id = m.id WHERE cma.category_id = ? ORDER BY m.last_read DESC',
                (selected_category_id,)
            ).fetchall()
        elif selected_category_id == -1:
            # Virtual category 'Uncategorized' is selected
            mangas_rows = db_conn.execute(
                'SELECT id FROM mangas WHERE id not in (SELECT manga_id FROM categories_mangas_association) ORDER BY last_read DESC'
            ).fetchall()
        else:
            # Virtual category 'All' is selected
            mangas_rows = db_conn.execute('SELECT id FROM mangas ORDER BY last_read DESC').fetchall()

        if len(mangas_rows) == 0 and selected_category_id == 0:
            # Display start page
            self.show_page('start_page')

            return

        self.show_page('flowbox')

        # Clear library flowbox
        thumbnail = self.flowbox.get_first_child()
        while thumbnail:
            next_thumbnail = thumbnail.get_next_sibling()
            self.flowbox.remove(thumbnail)
            thumbnail = next_thumbnail

        # Populate flowbox with mangas
        self.compute_thumbnails_size()
        for row in mangas_rows:
            self.add_manga(Manga.get(row['id'], db_conn=db_conn))

        db_conn.close()

    def search(self, _search_entry):
        self.flowbox.invalidate_filter()

    def select_all(self, _action=None, _param=None):
        if self.page != 'flowbox':
            return

        if not self.selection_mode:
            self.enter_selection_mode()
        if not self.selection_mode:
            return

        thumbnail = self.flowbox.get_first_child()
        while thumbnail:
            if not thumbnail._selected and not thumbnail._filtered:
                thumbnail._selected = True
                self.flowbox.select_child(thumbnail)
            thumbnail = thumbnail.get_next_sibling()

    def show(self, invalidate_sort=False):
        self.window.left_button.set_icon_name('list-add-symbolic')

        if self.page == 'flowbox':
            if self.searchbar.get_search_mode():
                self.search_entry.grab_focus()

            if invalidate_sort:
                self.flowbox.invalidate_sort()

        self.update_headerbar_buttons()

        self.window.menu_button.set_menu_model(self.builder.get_object('menu'))
        self.window.menu_button.set_icon_name('open-menu-symbolic')
        self.window.menu_button.show()

        self.window.show_page('library', True)

    def show_page(self, name):
        if self.page == name:
            return

        self.stack.set_visible_child_name(name)
        self.update_headerbar_buttons()

        self.page = name

    def toggle_flap(self, _button):
        self.flap.set_reveal_flap(not self.flap.get_reveal_flap())

    def toggle_search_mode(self):
        self.searchbar.set_search_mode(not self.searchbar.get_search_mode())

    def toggle_selected_read_status(self, _action, _param, read):
        chapters_ids = []
        chapters_data = []

        self.window.activity_indicator.start()

        for thumbnail in self.flowbox.get_selected_children():
            for chapter in thumbnail.manga.chapters:
                last_page_read_index = None
                if chapter.pages:
                    pages = deepcopy(chapter.pages)
                    for page in pages:
                        page['read'] = read
                else:
                    pages = None
                    last_page_read_index = None if chapter.read == read == 0 else chapter.last_page_read_index

                chapters_ids.append(chapter.id)
                chapters_data.append(dict(
                    pages=pages,
                    read=read,
                    recent=False,
                    last_page_read_index=last_page_read_index,
                ))

        db_conn = create_db_connection()
        with db_conn:
            update_rows(db_conn, 'chapters', chapters_ids, chapters_data)
        db_conn.close()

        self.window.activity_indicator.stop()
        self.leave_selection_mode()

    def update_all(self, _action, _param):
        self.window.updater.update_library()

    def update_headerbar_buttons(self):
        if self.page == 'flowbox':
            self.flap_reveal_button.show()
            self.window.right_button_stack.show()
            self.window.right_button_stack.set_visible_child_name('library')
        else:
            self.flap_reveal_button.hide()
            self.window.right_button_stack.hide()

    def update_selected(self, _action, _param):
        self.window.updater.add([thumbnail.manga for thumbnail in self.flowbox.get_selected_children()])
        self.window.updater.start()

        self.leave_selection_mode()

    def update_subtitle(self, *args, db_conn=None):
        nb_selected = len(self.flowbox.get_selected_children()) if self.selection_mode else 0
        if nb_selected > 0:
            subtitle = n_('{0} selected', '{0} selected', nb_selected).format(nb_selected)
        else:
            subtitle = _('Library')
            if (category_id := Settings.get_default().selected_category) != 0:
                if category_id == -1:
                    subtitle = '{0} / {1}'.format(subtitle, _('Uncategorized'))
                else:
                    subtitle = f'{subtitle} / {Category.get(category_id, db_conn).label}'

        self.subtitle_label.set_label(subtitle)


class CategoriesList(GObject.GObject):
    edit_mode = False  # mode to edit categories (of a manga selection) in bulk

    def __init__(self, library):
        GObject.Object.__init__(self)

        self.library = library
        self.listbox = self.library.window.library_categories_listbox
        self.stack = self.library.window.library_categories_stack
        self.edit_mode_buttonbox = self.library.window.library_categories_edit_mode_buttonbox

        self.listbox.connect('row-activated', self.on_category_activated)
        self.library.window.library_categories_edit_mode_ok_button.connect('clicked', self.on_edit_mode_ok_button_clicked)
        self.library.window.library_categories_edit_mode_cancel_button.connect('clicked', self.on_edit_mode_cancel_button_clicked)

    def clear(self):
        row = self.listbox.get_first_child()
        while row:
            self.listbox.remove(row)
            row = row.get_next_sibling()

    def enter_edit_mode(self):
        self.populate(edit_mode=True)

        self.library.flap.set_modal(False)
        self.library.flap.set_reveal_flap(True)
        self.library.flap.set_modal(True)

    def leave_edit_mode(self, refresh_library=False):
        self.library.flap.set_reveal_flap(False)

        self.populate(refresh_library=refresh_library)

    def on_category_activated(self, _listbox, row):
        if self.edit_mode:
            return

        Settings.get_default().selected_category = row.category.id if isinstance(row.category, Category) else row.category

        self.listbox.unselect_all()
        self.listbox.select_row(row)

        self.library.populate()

    def on_edit_mode_cancel_button_clicked(self, _button):
        self.library.flap.set_reveal_flap(False)

    def on_edit_mode_ok_button_clicked(self, _button):
        def run():
            insert_data = []
            delete_data = []

            # List of selected manga
            manga_ids = []
            for thumbnail in self.library.flowbox.get_selected_children():
                manga_ids.append(thumbnail.manga.id)

            for row in self.listbox.get_children():
                if row.get_activatable_widget().get_active():
                    if Settings.get_default().selected_category == row.category.id:
                        # No insert, we are sure that category is already associated with all selected manga
                        continue

                    associated_manga_ids = row.category.mangas
                    for manga_id in manga_ids:
                        if manga_id in associated_manga_ids:
                            # No insert, category is already associated with this manga
                            continue

                        insert_data.append(dict(
                            manga_id=manga_id,
                            category_id=row.category.id,
                        ))
                elif Settings.get_default().selected_category == row.category.id:
                    for manga_id in manga_ids:
                        delete_data.append(dict(
                            manga_id=manga_id,
                            category_id=row.category.id,
                        ))

            db_conn = create_db_connection()
            with db_conn:
                if insert_data:
                    insert_rows(db_conn, 'categories_mangas_association', insert_data)
                if delete_data:
                    delete_rows(db_conn, 'categories_mangas_association', delete_data)

            db_conn.close()

            GLib.idle_add(complete)

        def complete():
            self.library.window.activity_indicator.stop()
            # Leave library section mode, leave edit mode and refresh library
            self.library.leave_selection_mode('refresh_library')

        self.library.window.activity_indicator.start()

        thread = threading.Thread(target=run)
        thread.daemon = True
        thread.start()

    def populate(self, edit_mode=False, refresh_library=False):
        db_conn = create_db_connection()
        categories = db_conn.execute('SELECT * FROM categories ORDER BY label ASC').fetchall()
        nb_categorized = db_conn.execute('SELECT count(*) FROM categories_mangas_association').fetchone()[0]
        db_conn.close()

        if not categories and edit_mode:
            return

        self.clear()

        if edit_mode:
            self.edit_mode = True
            self.edit_mode_buttonbox.show()
        else:
            self.edit_mode = False
            self.edit_mode_buttonbox.hide()

        if categories:
            self.stack.set_visible_child_name('list')

            items = ['all'] + categories
            if nb_categorized > 0:
                items += ['uncategorized']

            for item in items:
                if item == 'all':
                    if edit_mode:
                        continue

                    category = 0
                    label = _('All')
                elif item == 'uncategorized':
                    if edit_mode:
                        continue

                    category = -1
                    label = _('Uncategorized')
                else:
                    category = Category.get(item['id'])
                    label = category.label

                row = Adw.ActionRow(visible=True, activatable=True)
                row.category = category
                row.set_title(label)
                row.set_title_lines(2)
                row.set_hexpand(False)

                if (isinstance(category, Category) and Settings.get_default().selected_category == category.id) or \
                    (isinstance(category, int) and Settings.get_default().selected_category == category):
                    self.listbox.select_row(row)

                if edit_mode:
                    switch = Gtk.Switch(visible=True)
                    switch.set_active(Settings.get_default().selected_category == category.id)
                    switch.set_valign(Gtk.Align.CENTER)
                    row.set_activatable_widget(switch)
                    row.add(switch)

                self.listbox.append(row)
        else:
            Settings.get_default().selected_category = 0
            self.stack.set_visible_child_name('empty')

        if refresh_library:
            self.library.populate()


class Thumbnail(Gtk.FlowBoxChild):
    __gtype_name__ = "Thumbnail"

    def __init__(self, parent, manga, width, height, nb_columns, **kwargs):
        super().__init__(**kwargs)

        self.parent = parent
        self.window = parent.window
        self.manga = manga

        self._cover_pixbuf = None
        self._server_logo_pixbuf = None
        self._filtered = False
        self._selected = False

        self.overlay = Gtk.Overlay()

        self.drawing_area = Gtk.DrawingArea()
        self.drawing_area.set_draw_func(self._draw)
        self.overlay.set_child(self.drawing_area)

        self.name_label = Gtk.Label(xalign=0, hexpand=True)
        self.name_label.get_style_context().add_class('library-manga-name-label')
        self.name_label.set_valign(Gtk.Align.END)
        self.name_label.set_wrap(True)
        self.overlay.add_overlay(self.name_label)

        self.set_child(self.overlay)
        self.resize(width, height)
        self._draw_name()

    def _draw(self, _drawing_area, context, _width, _height):
        context.save()

        self._draw_cover(context)
        self._draw_badges(context)
        self._draw_server_logo(context)

        context.restore()

    def _draw_badges(self, context):
        """
        Draws badges in top right corner of cover
        * Unread chapter: green
        * Recent chapters: blue
        * Downloaded chapters: red
        """
        nb_unread_chapters = self.manga.nb_unread_chapters
        nb_recent_chapters = self.manga.nb_recent_chapters
        nb_downloaded_chapters = self.manga.nb_downloaded_chapters

        if nb_unread_chapters == nb_recent_chapters == nb_downloaded_chapters == 0:
            return

        spacing = 5  # with top and right borders, between badges
        x = self.width

        context.set_font_size(13)

        def draw_badge(nb, color_r, color_g, color_b):
            nonlocal x

            if nb == 0:
                return

            text = str(nb)
            text_extents = context.text_extents(text)
            width = text_extents.x_advance + 2 * 3 + 1
            height = text_extents.height + 2 * 5

            # Draw rectangle
            x = x - spacing - width
            context.set_source_rgb(color_r, color_g, color_b)
            context.rectangle(x, spacing, width, height)
            context.fill()

            # Draw number
            context.set_source_rgb(1, 1, 1)
            context.move_to(x + 3, height)
            context.show_text(text)

        draw_badge(nb_unread_chapters, 0.2, 0.5, 0)        # #338000
        draw_badge(nb_recent_chapters, 0.2, 0.6, 1)        # #3399FF
        draw_badge(nb_downloaded_chapters, 1, 0.266, 0.2)  # #FF4433

    def _draw_cover(self, context):
        if self._cover_pixbuf is None:
            if self.manga.cover_fs_path is None:
                self._cover_pixbuf = Pixbuf.new_from_resource('/info/febvre/Komikku/images/missing_file.png')
            else:
                try:
                    if get_file_mime_type(self.manga.cover_fs_path) != 'image/gif':
                        self._cover_pixbuf = Pixbuf.new_from_file_at_scale(self.manga.cover_fs_path, 200, -1, True)
                    else:
                        animation_pixbuf = scale_pixbuf_animation(PixbufAnimation.new_from_file(self.manga.cover_fs_path), 200, -1, True)
                        self._cover_pixbuf = animation_pixbuf.get_static_image()
                except Exception:
                    # Invalid image, corrupted image, unsupported image format,...
                    self._cover_pixbuf = Pixbuf.new_from_resource('/info/febvre/Komikku/images/missing_file.png')

        pixbuf = self._cover_pixbuf.scale_simple(self.width, self.height, InterpType.BILINEAR)

        radius = 6
        arc_0 = 0
        arc_1 = math.pi * 0.5
        arc_2 = math.pi
        arc_3 = math.pi * 1.5

        context.new_sub_path()
        context.arc(self.width - radius, radius, radius, arc_3, arc_0)
        context.arc(self.width - radius, self.height - radius, radius, arc_0, arc_1)
        context.arc(radius, self.height - radius, radius, arc_1, arc_2)
        context.arc(radius, radius, radius, arc_2, arc_3)
        context.close_path()

        context.clip()

        Gdk.cairo_set_source_pixbuf(context, pixbuf, 0, 0)
        context.paint()

    def _draw_name(self):
        self.name_label.set_text(self.manga.name)

    def _draw_server_logo(self, context):
        if self._server_logo_pixbuf is None:
            logo_path = self.manga.server.logo_path
            if logo_path is not None:
                self._server_logo_pixbuf = Pixbuf.new_from_file_at_scale(
                    logo_path, 20 * self.window.hidpi_scale, 20 * self.window.hidpi_scale, True)
            else:
                self._server_logo_pixbuf = 0

        if self._server_logo_pixbuf:
            surface = create_cairo_surface_from_pixbuf(self._server_logo_pixbuf, self.window.hidpi_scale)
            context.set_source_surface(surface, 4, 4)
            context.paint()

    def resize(self, width, height):
        self.width = width
        self.height = height

        self.drawing_area.set_content_width(self.width)
        self.drawing_area.set_content_height(self.height)

    def update(self, manga):
        self.manga = manga
        self._cover_pixbuf = None

        self._draw_name()
        # Schedule a redraw to update drawing areas (cover, server logo and badges)
        self.queue_draw()
