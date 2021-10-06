# Copyright (C) 2019-2021 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-only or GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

import datetime
from gettext import gettext as _
import pytz

from gi.repository import Gdk
from gi.repository import GLib
from gi.repository import GObject
from gi.repository import Gtk
from gi.repository import Handy
from gi.repository.GdkPixbuf import Pixbuf
from gi.repository.GdkPixbuf import PixbufAnimation

from komikku.models import Chapter
from komikku.models import create_db_connection
from komikku.servers.utils import get_file_mime_type
from komikku.utils import scale_pixbuf_animation

THUMB_WIDTH = 45
THUMB_HEIGHT = 62
DAYS_LIMIT = 30


@Gtk.Template.from_resource('/info/febvre/Komikku/ui/history.ui')
class History(Gtk.Box):
    __gtype_name__ = 'History'

    stack = Gtk.Template.Child('stack')
    dates_box = Gtk.Template.Child('dates_box')
    searchbar = Gtk.Template.Child('searchbar')
    searchentry = Gtk.Template.Child('searchentry')

    def __init__(self, window):
        Gtk.ScrolledWindow.__init__(self)

        self.window = window
        self.builder = window.builder

        self.search_button = self.window.history_search_button
        self.searchbar.connect_entry(self.searchentry)
        self.searchbar.bind_property(
            'search-mode-enabled', self.search_button, 'active', GObject.BindingFlags.BIDIRECTIONAL | GObject.BindingFlags.SYNC_CREATE
        )
        self.searchentry.connect('activate', self.on_searchentry_activated)
        self.searchentry.connect('changed', self.search)

        self.search_button.connect('clicked', self.toggle_search)

        self.window.connect('key-press-event', self.on_key_press)
        self.window.stack.add_named(self, 'history')

    def filter(self, row):
        """
        This function gets one row and has to return:
        - True if the row should be displayed
        - False if the row should not be displayed
        """
        term = self.searchentry.get_text().strip().lower()

        ret = (
            term in row.chapter.title.lower() or
            term in row.chapter.manga.name.lower()
        )

        if ret:
            # As soon as a row is visible, made grand parent date_box visible
            GLib.idle_add(row.get_parent().get_parent().show)

        return ret

    def navigate_back(self, source):
        # Back to Library if:
        # - user click on 'Back' button
        # - or use 'Esc' key and not in search mode
        if source == 'click' or not self.searchbar.get_search_mode():
            self.window.library.show()

        # Leave search mode
        if self.searchbar.get_search_mode():
            self.searchbar.set_search_mode(False)

    def on_key_press(self, _widget, event):
        """Search entry can be focused by simply typing a printable character"""

        if self.window.page != 'history':
            return Gdk.EVENT_PROPAGATE

        return self.searchbar.handle_event(event)

    def on_searchentry_activated(self, _entry):
        if not self.searchbar.get_search_mode():
            return

        row = self.dates_box.get_children()[0].get_children()[-1].get_row_at_y(0)
        if row:
            self.window.reader.init(row.chapter.manga, row.chapter)

    def populate(self):
        for box in self.dates_box:
            box.destroy()

        db_conn = create_db_connection()
        start = (datetime.date.today() - datetime.timedelta(days=DAYS_LIMIT)).strftime('%Y-%m-%d')
        records = db_conn.execute('SELECT * FROM chapters WHERE last_read >= ? ORDER BY last_read DESC', (start,)).fetchall()
        db_conn.close()

        if records:
            local_timezone = datetime.datetime.utcnow().astimezone().tzinfo
            today = datetime.date.today()
            yesterday = today - datetime.timedelta(days=1)

            date = None
            for record in records:
                chapter = Chapter.get(record['id'])

                # Create new Box (Label + ListBox) when date change
                if date is None or date != chapter.last_read.date():
                    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

                    date = chapter.last_read.date()
                    if date == today:
                        label = _('Today')
                    elif date == yesterday:
                        label = _('Yesterday')
                    else:
                        label = date.strftime(_('%Y-%m-%d'))
                    label = Gtk.Label(label=label, xalign=0, margin=6)
                    label.get_style_context().add_class('title-4')
                    label.get_style_context().add_class('dim-label')
                    box.add(label)

                    listbox = Gtk.ListBox()
                    listbox.get_style_context().add_class('content')
                    listbox.set_filter_func(self.filter)
                    box.add(listbox)

                    self.dates_box.add(box)

                action_row = Handy.ActionRow(activatable=True, selectable=False)
                action_row.connect('activated', self.on_row_activated)
                action_row.chapter = chapter

                action_row.set_title(chapter.manga.name)
                action_row.set_subtitle(chapter.title)

                # Cover
                if chapter.manga.cover_fs_path is None:
                    pixbuf = Pixbuf.new_from_resource_at_scale(
                        '/info/febvre/Komikku/images/missing_file.png', THUMB_WIDTH, THUMB_HEIGHT, False)
                else:
                    try:
                        if get_file_mime_type(chapter.manga.cover_fs_path) != 'image/gif':
                            pixbuf = Pixbuf.new_from_file_at_scale(chapter.manga.cover_fs_path, THUMB_WIDTH, THUMB_HEIGHT, False)
                        else:
                            animation_pixbuf = scale_pixbuf_animation(
                                PixbufAnimation.new_from_file(chapter.manga.cover_fs_path), THUMB_WIDTH, THUMB_HEIGHT, False)
                            pixbuf = animation_pixbuf.get_static_image()
                    except Exception:
                        # Invalid image, corrupted image, unsupported image format,...
                        pixbuf = Pixbuf.new_from_resource_at_scale(
                            '/info/febvre/Komikku/images/missing_file.png', THUMB_WIDTH, THUMB_HEIGHT, False)

                action_row.add_prefix(Gtk.Image.new_from_pixbuf(pixbuf))

                # Time
                last_read = chapter.last_read.replace(tzinfo=pytz.UTC).astimezone(local_timezone)
                label = Gtk.Label(label=last_read.strftime('%H:%M'))
                label.get_style_context().add_class('subtitle')
                action_row.add(label)

                # Play button
                button = Gtk.Button.new_from_icon_name('media-playback-start-symbolic', Gtk.IconSize.BUTTON)
                button.connect('clicked', self.on_row_play_button_clicked, action_row)
                button.set_valign(Gtk.Align.CENTER)
                action_row.add(button)

                listbox.add(action_row)

            self.dates_box.show_all()
            self.stack.set_visible_child_name('list')
        else:
            self.stack.set_visible_child_name('empty')

    def on_row_activated(self, row):
        self.window.card.init(row.chapter.manga)

    def on_row_play_button_clicked(self, _button, row):
        self.window.reader.init(row.chapter.manga, row.chapter)

    def search(self, _entry):
        for date_box in self.dates_box.get_children():
            listbox = date_box.get_children()[1]
            listbox.invalidate_filter()
            # Hide date_box, will be shown if a least one row of listbox is not filtered
            date_box.hide()

    def show(self, transition=True):
        self.populate()

        self.window.left_button.set_tooltip_text(_('Back'))
        self.window.left_button_image.set_from_icon_name('go-previous-symbolic', Gtk.IconSize.BUTTON)
        self.window.library_flap_reveal_button.hide()

        self.window.right_button_stack.set_visible_child_name('history')

        self.window.menu_button.hide()

        self.window.show_page('history', transition=transition)

    def toggle_search(self, button):
        self.searchbar.set_search_mode(button.get_active())
