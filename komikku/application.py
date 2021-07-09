# Copyright (C) 2019-2021 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-only or GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from gettext import gettext as _
import gi
import logging
import sys
from threading import Timer
import time

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
gi.require_version('Notify', '0.7')

from gi.repository import Adw
from gi.repository import Gdk
from gi.repository import Gio
from gi.repository import GLib
from gi.repository import Gtk
from gi.repository import Notify
from gi.repository.GdkPixbuf import Pixbuf

from komikku.activity_indicator import ActivityIndicator
from komikku.card import Card
from komikku.categories_editor import CategoriesEditor
from komikku.downloader import Downloader
from komikku.downloader import DownloadManager
from komikku.explorer import Explorer
from komikku.library import Library
from komikku.models import backup_db
from komikku.models import Settings
from komikku.preferences import Preferences
from komikku.reader import Reader
from komikku.servers import get_allowed_servers_list
from komikku.updater import Updater

CREDITS = dict(
    developers=('Valéry Febvre (valos)', ),
    contributors=(
        'Mufeed Ali (fushinari)',
        'Gerben Droogers (Tijder)',
        'GrownNed',
        'ISO-morphism',
        'jaskaranSM',
        'Leo Prikler',
        'Romain Vaudois',
        'Arthur Williams (TAAPArthur)',
    ),
    translators=(
        'Ege Çelikçi (Turkish)',
        'Valéry Febvre (French)',
        'GrownNed (Russian)',
        'Leo Prikler (German)',
        'Mek101 (Italian)',
        'Heimen Stoffels (Dutch)',
        'VaGNaroK (Brazilian Portuguese)',
    ),
)


class Application(Gtk.Application):
    application_id = 'info.febvre.Komikku'
    development_mode = False
    logger = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, application_id=self.application_id, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE, **kwargs)

        self.window = None

        logging.basicConfig(
            format='%(asctime)s | %(levelname)s | %(name)s | %(message)s', datefmt='%d-%m-%y %H:%M:%S',
            level=logging.DEBUG if self.development_mode else logging.INFO
        )

        self.logger = logging.getLogger('komikku')

    def add_actions(self):
        self.window.add_actions()

    def add_accelerators(self):
        self.window.add_accelerators()

    def do_activate(self):
        if not self.window:
            self.window = ApplicationWindow(application=self, title='Komikku', icon_name=self.application_id)

            self.add_accelerators()
            self.add_actions()

        self.window.present()

    def do_command_line(self, command_line):
        self.do_activate()

        args = command_line.get_arguments()
        urls = args[1:]
        if not urls:
            return 0

        if len(urls) > 1:
            msg = _('Multiple URLs not supported')
            self.logger.warning(msg)
            self.window.show_notification(msg)

        url = urls[0]
        servers = []
        for data in get_allowed_servers_list(Settings.get_default()):
            server_class = getattr(data['module'], data['class_name'])
            if not server_class.base_url or not url.startswith(server_class.base_url):
                continue

            if initial_data := server_class.get_manga_initial_data_from_url(url):
                data['manga_initial_data'] = initial_data
                servers.append(data)

        if not servers:
            msg = _('Invalid URL {}, not handled by any server.').format(url)
            self.logger.info(msg)
            self.window.show_notification(msg)
        else:
            self.window.explorer.show(servers=servers)

        return 0

    def do_startup(self):
        Gtk.Application.do_startup(self)

        GLib.set_application_name(_('Komikku'))
        GLib.set_prgname(self.application_id)

        Adw.init()
        Notify.init(_('Komikku'))


@Gtk.Template.from_resource('/info/febvre/Komikku/ui/application_window.ui')
class ApplicationWindow(Adw.ApplicationWindow):
    __gtype_name__ = 'ApplicationWindow'

    hidpi_scale = 1
    mobile_width = False
    network_available = False
    page = None

    is_maximized = False
    is_fullscreen = False
    _prev_size = None

    headerbar_revealer = Gtk.Template.Child('headerbar_revealer')
    headerbar = Gtk.Template.Child('headerbar')
    left_button = Gtk.Template.Child('left_button')
    title_stack = Gtk.Template.Child('title_stack')
    right_button_stack = Gtk.Template.Child('right_button_stack')
    menu_button = Gtk.Template.Child('menu_button')

    box = Gtk.Template.Child('box')
    overlay = Gtk.Template.Child('overlay')
    stack = Gtk.Template.Child('stack')

    library_flap_reveal_button = Gtk.Template.Child('library_flap_reveal_button')
    library_search_button = Gtk.Template.Child('library_search_button')
    library_searchbar = Gtk.Template.Child('library_searchbar')
    library_search_menu_button = Gtk.Template.Child('library_search_menu_button')
    library_searchentry = Gtk.Template.Child('library_searchentry')
    library_subtitle_label = Gtk.Template.Child('library_subtitle_label')
    library_flap = Gtk.Template.Child('library_flap')
    library_stack = Gtk.Template.Child('library_stack')
    library_categories_stack = Gtk.Template.Child('library_categories_stack')
    library_categories_listbox = Gtk.Template.Child('library_categories_listbox')
    library_categories_edit_mode_buttonbox = Gtk.Template.Child('library_categories_edit_mode_buttonbox')
    library_categories_edit_mode_cancel_button = Gtk.Template.Child('library_categories_edit_mode_cancel_button')
    library_categories_edit_mode_ok_button = Gtk.Template.Child('library_categories_edit_mode_ok_button')
    library_flowbox = Gtk.Template.Child('library_flowbox')

    card_resume_read_button = Gtk.Template.Child('card_resume_read_button')
    card_viewswitchertitle = Gtk.Template.Child('card_viewswitchertitle')
    card_viewswitcherbar = Gtk.Template.Child('card_viewswitcherbar')
    card_stack = Gtk.Template.Child('card_stack')
    card_categories_stack = Gtk.Template.Child('card_categories_stack')
    card_categories_listbox = Gtk.Template.Child('card_categories_listbox')
    card_chapters_listbox = Gtk.Template.Child('card_chapters_listbox')
    card_info_box = Gtk.Template.Child('card_info_box')
    card_info_grid = Gtk.Template.Child('card_info_grid')
    card_name_label = Gtk.Template.Child('card_name_label')
    card_cover_image = Gtk.Template.Child('card_cover_image')
    card_authors_value_label = Gtk.Template.Child('card_authors_value_label')
    card_genres_value_label = Gtk.Template.Child('card_genres_value_label')
    card_status_value_label = Gtk.Template.Child('card_status_value_label')
    card_scanlators_value_label = Gtk.Template.Child('card_scanlators_value_label')
    card_server_value_label = Gtk.Template.Child('card_server_value_label')
    card_last_update_value_label = Gtk.Template.Child('card_last_update_value_label')
    card_synopsis_value_label = Gtk.Template.Child('card_synopsis_value_label')
    card_more_label = Gtk.Template.Child('card_more_label')

    reader_fullscreen_button = Gtk.Template.Child('reader_fullscreen_button')
    reader_overlay = Gtk.Template.Child('reader_overlay')
    reader_scrolledwindow = Gtk.Template.Child('reader_scrolledwindow')
    reader_viewport = Gtk.Template.Child('reader_viewport')
    reader_title_label = Gtk.Template.Child('reader_title_label')
    reader_subtitle_label = Gtk.Template.Child('reader_subtitle_label')

    download_manager_subtitle_label = Gtk.Template.Child('download_manager_subtitle_label')
    download_manager_start_stop_button = Gtk.Template.Child('download_manager_start_stop_button')

    explorer_title_label = Gtk.Template.Child('explorer_title_label')
    explorer_servers_page_search_button = Gtk.Template.Child('explorer_servers_page_search_button')
    explorer_search_page_server_website_button = Gtk.Template.Child('explorer_search_page_server_website_button')
    explorer_card_page_add_read_button = Gtk.Template.Child('explorer_card_page_add_read_button')

    preferences_subtitle_label = Gtk.Template.Child('preferences_subtitle_label')

    notification_label = Gtk.Template.Child('notification_label')
    notification_revealer = Gtk.Template.Child('notification_revealer')

    app_logo = Gtk.Template.Child('app_logo')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.application = kwargs['application']

        self.hidpi_scale = self.get_scale_factor()

        self._night_light_handler_id = 0
        self._night_light_proxy = None

        self.builder = Gtk.Builder()
        self.builder.add_from_resource('/info/febvre/Komikku/ui/menu/main.xml')

        self.logging_manager = self.application.logger
        self.downloader = Downloader(self)
        self.updater = Updater(self)

        self.activity_indicator = ActivityIndicator()
        self.overlay.add_overlay(self.activity_indicator)

        Gio.NetworkMonitor.get_default().connect('network-changed', self.on_network_status_changed)
        # Non-portal implementations of Gio.NetworkMonitor (app not running under Flatpak) don't actually change the value
        # unless the network state actually changes
        Gio.NetworkMonitor.get_default().emit('network-changed', None)

        self.assemble_window()

    def add_accelerators(self):
        self.application.set_accels_for_action('app.add', ['<Control>plus'])
        self.application.set_accels_for_action('app.enter-search-mode', ['<Control>f'])
        self.application.set_accels_for_action('app.fullscreen', ['F11'])
        self.application.set_accels_for_action('app.select-all', ['<Control>a'])
        self.application.set_accels_for_action('app.preferences', ['<Control>p'])
        self.application.set_accels_for_action('app.shortcuts', ['<Control>question'])

        self.reader.add_accelerators()

    def add_actions(self):
        about_action = Gio.SimpleAction.new('about', None)
        about_action.connect('activate', self.on_about_menu_clicked)
        self.application.add_action(about_action)

        add_action = Gio.SimpleAction.new('add', None)
        add_action.connect('activate', self.on_left_button_clicked)
        self.application.add_action(add_action)

        enter_search_mode_action = Gio.SimpleAction.new('enter-search-mode', None)
        enter_search_mode_action.connect('activate', self.enter_search_mode)
        self.application.add_action(enter_search_mode_action)

        fullscreen_action = Gio.SimpleAction.new('fullscreen', None)
        fullscreen_action.connect('activate', self.toggle_fullscreen)
        self.application.add_action(fullscreen_action)

        self.select_all_action = Gio.SimpleAction.new('select-all', None)
        self.select_all_action.connect('activate', self.select_all)
        self.application.add_action(self.select_all_action)

        preferences_action = Gio.SimpleAction.new('preferences', None)
        preferences_action.connect('activate', self.on_preferences_menu_clicked)
        self.application.add_action(preferences_action)

        shortcuts_action = Gio.SimpleAction.new('shortcuts', None)
        shortcuts_action.connect('activate', self.on_shortcuts_menu_clicked)
        self.application.add_action(shortcuts_action)

        self.library.add_actions()
        self.card.add_actions()
        self.reader.add_actions()
        self.download_manager.add_actions()

    def assemble_window(self):
        # Default size
        window_size = Settings.get_default().window_size
        self.set_default_size(window_size[0], window_size[1])

        # Titlebar
        self.left_button.connect('clicked', self.on_left_button_clicked)

        # Fisrt start grid
        pix = Pixbuf.new_from_resource_at_scale('/info/febvre/Komikku/images/logo.png', 256, 256, True)
        self.app_logo.set_from_pixbuf(pix)

        # Init stack pages
        self.library = Library(self)
        self.card = Card(self)
        self.reader = Reader(self)
        self.categories_editor = CategoriesEditor(self)
        self.download_manager = DownloadManager(self)
        self.explorer = Explorer(self)
        self.preferences = Preferences(self)

        # Window
        self.connect('notify::default-width', self.on_resize)
        self.controller_key = Gtk.EventControllerKey.new()
        self.controller_key.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        self.add_controller(self.controller_key)
        self.controller_key.connect('key-pressed', self.on_key_pressed)

        # self.connect('notify::default-height', self.on_resize)
        # self.connect('delete-event', self.on_application_quit)
        # self.connect('window-state-event', self.on_window_state_event)
        self.headerbar_revealer.connect('notify::child-revealed', self.on_headerbar_toggle)

        # Custom CSS
        css_provider = Gtk.CssProvider()
        css_provider_resource = Gio.File.new_for_uri('resource:///info/febvre/Komikku/css/style.css')
        css_provider.load_from_file(css_provider_resource)
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        if Gio.Application.get_default().development_mode is True:
            self.get_style_context().add_class('devel')

        # Theme (light or dark)
        self.init_theme()

        self.library.show()

    def confirm(self, title, message, callback):
        def on_response(dialog, response_id):
            if response_id == Gtk.ResponseType.YES:
                callback()

            dialog.destroy()

        dialog = Gtk.Dialog.new()
        dialog.set_transient_for(self)
        dialog.set_modal(True)
        dialog.get_style_context().add_class('solid-csd')
        dialog.connect('response', on_response)
        dialog.set_title(title)
        dialog.add_buttons(_('Yes'), Gtk.ResponseType.YES, _('Cancel'), Gtk.ResponseType.CANCEL)
        dialog.set_default_response(Gtk.ResponseType.YES)

        label = Gtk.Label(vexpand=True, margin_start=16, margin_top=16, margin_end=16, margin_bottom=16)
        label.set_text(message)
        label.set_wrap(True)
        label.set_vexpand(True)
        label.set_valign(Gtk.Align.CENTER)
        label.set_halign(Gtk.Align.CENTER)
        label.set_justify(Gtk.Justification.CENTER)
        dialog.get_content_area().append(label)
        dialog.present()

    def enter_search_mode(self, action, param):
        if self.page == 'library':
            self.library.toggle_search_mode()

    def hide_notification(self):
        self.notification_revealer.set_reveal_child(False)

    def init_theme(self):
        if Settings.get_default().night_light and not self._night_light_proxy:
            # Watch night light changes
            self._night_light_proxy = Gio.DBusProxy.new_sync(
                Gio.bus_get_sync(Gio.BusType.SESSION, None),
                Gio.DBusProxyFlags.NONE,
                None,
                'org.gnome.SettingsDaemon.Color',
                '/org/gnome/SettingsDaemon/Color',
                'org.gnome.SettingsDaemon.Color',
                None
            )

            def property_changed(proxy, changed_properties, invalidated_properties):
                properties = changed_properties.unpack()
                if 'NightLightActive' in properties.keys():
                    Gtk.Settings.get_default().set_property('gtk-application-prefer-dark-theme', properties['NightLightActive'])

            self._night_light_handler_id = self._night_light_proxy.connect('g-properties-changed', property_changed)

            Gtk.Settings.get_default().set_property(
                'gtk-application-prefer-dark-theme',
                self._night_light_proxy.get_cached_property('NightLightActive')
            )
        else:
            if self._night_light_proxy and self._night_light_handler_id > 0:
                self._night_light_proxy.disconnect(self._night_light_handler_id)
                self._night_light_proxy = None
                self._night_light_handler_id = 0

            Gtk.Settings.get_default().set_property('gtk-application-prefer-dark-theme', Settings.get_default().dark_theme)

    def on_about_menu_clicked(self, action, param):
        builder = Gtk.Builder.new_from_resource('/info/febvre/Komikku/about_dialog.ui')
        dialog = builder.get_object('about_dialog')
        dialog.set_authors([
            *CREDITS['developers'], '',

            _('Contributors: Code, Patches, Debugging:'), '',
            *CREDITS['contributors'], '',
        ])
        dialog.set_translator_credits('\n'.join(CREDITS['translators']))
        dialog.set_modal(True)
        dialog.set_transient_for(self)
        dialog.present()

    def on_application_quit(self, window, event):
        def quit():
            self.save_window_size()
            backup_db()

            self.application.quit()

        if self.downloader.running or self.updater.running:
            def confirm_callback():
                self.downloader.stop()
                self.updater.stop()

                while self.downloader.running or self.updater.running:
                    time.sleep(0.1)
                    continue

                quit()

            message = [
                _('Are you sure you want to quit?'),
            ]
            if self.downloader.running:
                message.append(_('Some chapters are currently being downloaded.'))
            if self.updater.running:
                message.append(_('Some mangas are currently being updated.'))

            self.confirm(
                _('Quit?'),
                '\n'.join(message),
                confirm_callback
            )

            return

        quit()

    def on_headerbar_toggle(self, *args):
        if self.page == 'reader' and self.reader.pager:
            self.reader.pager.resize_pages()

    def on_key_pressed(self, _controller, keyval, _keycode, _state):
        """
        Go back navigation with <Escape> key:
        - Library <- Manga <- Reader
        - Explorer: Library <- Servers <- Search <- Card
        - Preferences: Library <- Page <- Subpage
        - Categories Editor: Library <-
        - Exit selection mode: Library, Card chapters, Download Manager
        - Exit search mode: Library, Explorer 'servers' and 'search' pages
        """
        if keyval == Gdk.KEY_Escape:
            self.on_left_button_clicked()
            return Gdk.EVENT_STOP

        return Gdk.EVENT_PROPAGATE

    def on_left_button_clicked(self, action_or_button=None, _param=None):
        if type(action_or_button) == Gio.SimpleAction:
            source = 'shortcut'
        elif type(action_or_button) == Gtk.Button:
            source = 'click'
        else:
            source = 'esc-key'

        if self.page == 'library':
            if source in ('click', 'shortcut') and not self.library.selection_mode:
                self.explorer.show()
            if self.library.selection_mode:
                self.library.leave_selection_mode()
            if source == 'esc-key':
                self.library.searchbar.set_search_mode(False)

        elif self.page == 'card':
            if self.card.selection_mode:
                self.card.leave_selection_mode()
            else:
                self.card.stop_populate()
                self.library.show(invalidate_sort=True)

        elif self.page == 'reader':
            self.reader.remove_pager()
            self.set_unfullscreen()

            # Refresh to update all previously chapters consulted (last page read may have changed)
            # and update info like disk usage
            self.card.refresh(self.reader.chapters_consulted)
            self.card.show()

        elif self.page == 'categories_editor':
            self.library.show()

        elif self.page == 'download_manager':
            if self.download_manager.selection_mode:
                self.download_manager.leave_selection_mode()
            else:
                self.library.show()

        elif self.page == 'explorer':
            self.explorer.navigate_back(source)

        elif self.page == 'preferences':
            self.preferences.navigate_back(source)

    def on_network_status_changed(self, monitor, _connected):
        self.network_available = monitor.get_connectivity() == Gio.NetworkConnectivity.FULL

        if self.network_available:
            # Automatically update library at startup
            if Settings.get_default().update_at_startup and not self.updater.update_at_startup_done:
                self.updater.update_library(startup=True)

            # Start Downloader
            if Settings.get_default().downloader_state:
                self.downloader.start()
        else:
            # Stop Updater
            self.updater.stop()

            # Stop Downloader
            if Settings.get_default().downloader_state:
                self.downloader.stop()

    def on_resize(self, _window, _allocation):
        size = dict(
            width=self.get_size(Gtk.Orientation.HORIZONTAL),
            height=self.get_size(Gtk.Orientation.VERTICAL),
        )
        if self._prev_size and self._prev_size['width'] == size['width'] and self._prev_size['height'] == size['height']:
            return

        self._prev_size = size

        self.library.on_resize()
        if self.page == 'reader':
            self.reader.on_resize()

        self.mobile_width = size['width'] <= 800

    def on_preferences_menu_clicked(self, action, param):
        self.preferences.show()

    def on_shortcuts_menu_clicked(self, action, param):
        builder = Gtk.Builder()
        builder.add_from_resource('/info/febvre/Komikku/ui/shortcuts_overview.ui')

        shortcuts_overview = builder.get_object('shortcuts_overview')
        shortcuts_overview.set_modal(True)
        shortcuts_overview.set_transient_for(self)
        shortcuts_overview.present()

    def on_window_state_event(self, widget, event):
        self.is_maximized = (event.new_window_state & Gdk.WindowState.MAXIMIZED) != 0
        self.is_fullscreen = (event.new_window_state & Gdk.WindowState.FULLSCREEN) != 0

    def save_window_size(self):
        if not self.is_maximized and not self.is_fullscreen:
            size = self.get_size()
            Settings.get_default().window_size = [size.width, size.height]

    def select_all(self, action, param):
        if self.page == 'library':
            self.library.select_all()
        elif self.page == 'card':
            self.card.chapters_list.select_all()

    def set_fullscreen(self):
        if not self.is_fullscreen:
            self.reader.controls.on_fullscreen()
            self.fullscreen()

    def set_unfullscreen(self):
        if self.is_fullscreen:
            self.reader.controls.on_unfullscreen()
            self.unfullscreen()

    def show_notification(self, message, interval=5):
        self.notification_label.set_text(message)
        self.notification_revealer.set_reveal_child(True)

        revealer_timer = Timer(interval, GLib.idle_add, args=[self.hide_notification])
        revealer_timer.start()

    def show_page(self, name, transition=True):
        self.activity_indicator.stop()

        if not transition:
            transition_type = Gtk.StackTransitionType.NONE
        elif name in ('categories_editor', 'download_manager', 'explorer', 'preferences'):
            transition_type = Gtk.StackTransitionType.SLIDE_RIGHT
        else:
            if self.page in ('categories_editor', 'download_manager', 'explorer', 'preferences'):
                transition_type = Gtk.StackTransitionType.SLIDE_LEFT
            else:
                transition_type = self.stack.get_transition_type()

        self.stack.set_visible_child_full(name, transition_type)
        self.title_stack.set_visible_child_full(name, transition_type)

        self.page = name

    def toggle_fullscreen(self, *args):
        if self.is_fullscreen:
            self.set_unfullscreen()
        else:
            self.set_fullscreen()


if __name__ == '__main__':
    app = Application()
    app.run(sys.argv)
