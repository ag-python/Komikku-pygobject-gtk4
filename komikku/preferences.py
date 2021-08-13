# Copyright (C) 2019-2021 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-only or GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from gettext import gettext as _

from gi.repository import Adw
from gi.repository import Gtk

from komikku.models import Settings
from komikku.servers import get_server_main_id_by_id
from komikku.servers import get_servers_list
from komikku.servers import LANGUAGES
from komikku.utils import KeyringHelper


@Gtk.Template.from_resource('/info/febvre/Komikku/ui/preferences.ui')
class Preferences(Adw.Leaflet):
    __gtype_name__ = 'Preferences'

    window = NotImplemented
    settings = NotImplemented

    pages_stack = Gtk.Template.Child('pages_stack')
    subpages_stack = Gtk.Template.Child('subpages_stack')

    theme_switch = Gtk.Template.Child('theme_switch')
    night_light_switch = Gtk.Template.Child('night_light_switch')
    desktop_notifications_switch = Gtk.Template.Child('desktop_notifications_switch')

    update_at_startup_switch = Gtk.Template.Child('update_at_startup_switch')
    new_chapters_auto_download_switch = Gtk.Template.Child('new_chapters_auto_download_switch')
    nsfw_content_switch = Gtk.Template.Child('nsfw_content_switch')
    servers_languages_actionrow = Gtk.Template.Child('servers_languages_actionrow')
    servers_languages_subpage_group = Gtk.Template.Child('servers_languages_subpage_group')
    servers_settings_actionrow = Gtk.Template.Child('servers_settings_actionrow')
    servers_settings_subpage_group = Gtk.Template.Child('servers_settings_subpage_group')
    long_strip_detection_switch = Gtk.Template.Child('long_strip_detection_switch')

    reading_mode_row = Gtk.Template.Child('reading_mode_row')
    scaling_row = Gtk.Template.Child('scaling_row')
    background_color_row = Gtk.Template.Child('background_color_row')
    borders_crop_switch = Gtk.Template.Child('borders_crop_switch')
    fullscreen_switch = Gtk.Template.Child('fullscreen_switch')

    credentials_storage_plaintext_fallback_switch = Gtk.Template.Child('credentials_storage_plaintext_fallback_switch')

    def __init__(self, window):
        super().__init__()

        self.window = window
        self.subtitle_label = self.window.preferences_subtitle_label

        self.settings = Settings.get_default()

        self.set_config_values()

        self.window.stack.add_named(self, 'preferences')
        self.connect('notify::visible-child', self.on_page_changed)

    def navigate_back(self, source):
        if self.get_visible_child_name() == 'subpages':
            self.navigate(Adw.NavigationDirection.BACK)
        else:
            self.window.library.show()

    def on_background_color_changed(self, row, param):
        index = row.get_selected()

        if index == 0:
            self.settings.background_color = 'white'
        elif index == 1:
            self.settings.background_color = 'black'

    def on_borders_crop_changed(self, switch_button, _gparam):
        self.settings.borders_crop = switch_button.get_active()

    def on_credentials_storage_plaintext_fallback_changed(self, switch_button, _gparam):
        self.settings.credentials_storage_plaintext_fallback = switch_button.get_active()

    def on_desktop_notifications_changed(self, switch_button, _gparam):
        if switch_button.get_active():
            self.settings.desktop_notifications = True
        else:
            self.settings.desktop_notifications = False

    def on_fullscreen_changed(self, switch_button, _gparam):
        self.settings.fullscreen = switch_button.get_active()

    def on_long_strip_detection_changed(self, switch_button, _gparam):
        self.settings.long_strip_detection = switch_button.get_active()

    def on_new_chapters_auto_download_changed(self, switch_button, _gparam):
        if switch_button.get_active():
            self.settings.new_chapters_auto_download = True
        else:
            self.settings.new_chapters_auto_download = False

    def on_night_light_changed(self, switch_button, _gparam):
        self.settings.night_light = switch_button.get_active()

        self.window.init_theme()

    def on_nsfw_content_changed(self, switch_button, _gparam):
        if switch_button.get_active():
            self.settings.nsfw_content = True
        else:
            self.settings.nsfw_content = False

    def on_page_changed(self, _deck, _child):
        if self.get_visible_child_name() == 'subpages':
            self.subtitle_label.show()
        else:
            self.subtitle_label.hide()

    def on_reading_mode_changed(self, row, param):
        index = row.get_selected()

        if index == 0:
            self.settings.reading_mode = 'right-to-left'
        elif index == 1:
            self.settings.reading_mode = 'left-to-right'
        elif index == 2:
            self.settings.reading_mode = 'vertical'
        elif index == 3:
            self.settings.reading_mode = 'webtoon'

    def on_scaling_changed(self, row, param):
        index = row.get_selected()

        if index == 0:
            self.settings.scaling = 'screen'
        elif index == 1:
            self.settings.scaling = 'width'
        elif index == 2:
            self.settings.scaling = 'height'
        elif index == 3:
            self.settings.scaling = 'original'

    def on_servers_language_activated(self, switch_button, _gparam, code):
        if switch_button.get_active():
            self.settings.add_servers_language(code)
        else:
            self.settings.remove_servers_language(code)

    def on_theme_changed(self, switch_button, _gparam):
        self.settings.dark_theme = switch_button.get_active()

        self.window.init_theme()

    def on_update_at_startup_changed(self, switch_button, _gparam):
        if switch_button.get_active():
            self.settings.update_at_startup = True
        else:
            self.settings.update_at_startup = False

    def set_config_values(self):
        #
        # General
        #

        # Dark theme
        self.theme_switch.set_active(self.settings.dark_theme)
        self.theme_switch.connect('notify::active', self.on_theme_changed)

        # Night light
        self.night_light_switch.set_active(self.settings.night_light)
        self.night_light_switch.connect('notify::active', self.on_night_light_changed)

        # Desktop notifications
        self.desktop_notifications_switch.set_active(self.settings.desktop_notifications)
        self.desktop_notifications_switch.connect('notify::active', self.on_desktop_notifications_changed)

        #
        # Library
        #

        # Update manga at startup
        self.update_at_startup_switch.set_active(self.settings.update_at_startup)
        self.update_at_startup_switch.connect('notify::active', self.on_update_at_startup_changed)

        # Auto download new chapters
        self.new_chapters_auto_download_switch.set_active(self.settings.new_chapters_auto_download)
        self.new_chapters_auto_download_switch.connect('notify::active', self.on_new_chapters_auto_download_changed)

        # Servers languages
        self.servers_languages_subpage = PreferencesServersLanguagesSubpage(self)
        self.servers_languages_actionrow.props.activatable = True
        self.servers_languages_actionrow.connect('activated', self.servers_languages_subpage.present)

        # Servers settings
        self.servers_settings_subpage = PreferencesServersSettingsSubpage(self)
        self.servers_settings_actionrow.props.activatable = True
        self.servers_settings_actionrow.connect('activated', self.servers_settings_subpage.present)

        # Long strip detection
        self.long_strip_detection_switch.set_active(self.settings.long_strip_detection)
        self.long_strip_detection_switch.connect('notify::active', self.on_long_strip_detection_changed)

        # NSFW content
        self.nsfw_content_switch.set_active(self.settings.nsfw_content)
        self.nsfw_content_switch.connect('notify::active', self.on_nsfw_content_changed)

        #
        # Reader
        #

        # Reading mode
        self.reading_mode_row.set_selected(self.settings.reading_mode_value)
        self.reading_mode_row.connect('notify::selected', self.on_reading_mode_changed)

        # Image scaling
        self.scaling_row.set_selected(self.settings.scaling_value)
        self.scaling_row.connect('notify::selected', self.on_scaling_changed)

        # Background color
        self.background_color_row.set_selected(self.settings.background_color_value)
        self.background_color_row.connect('notify::selected', self.on_background_color_changed)

        # Borders crop
        self.borders_crop_switch.set_active(self.settings.borders_crop)
        self.borders_crop_switch.connect('notify::active', self.on_borders_crop_changed)

        # Full screen
        self.fullscreen_switch.set_active(self.settings.fullscreen)
        self.fullscreen_switch.connect('notify::active', self.on_fullscreen_changed)

        #
        # Advanced
        #

        # Credentials storage: allow plaintext as fallback
        self.credentials_storage_plaintext_fallback_switch.set_active(self.settings.credentials_storage_plaintext_fallback)
        self.credentials_storage_plaintext_fallback_switch.connect('notify::active', self.on_credentials_storage_plaintext_fallback_changed)

    def show(self, transition=True):
        self.window.left_button.set_icon_name('go-previous-symbolic')
        self.window.library_flap_reveal_button.hide()

        self.window.right_button_stack.hide()

        self.window.menu_button.hide()

        self.pages_stack.set_visible_child_name('general')
        self.window.show_page('preferences', transition=transition)


class PreferencesServersLanguagesSubpage:
    parent = NotImplemented
    settings = NotImplemented

    def __init__(self, parent):
        self.parent = parent
        self.settings = Settings.get_default()

        servers_languages = self.settings.servers_languages

        for code, language in LANGUAGES.items():
            action_row = Adw.ActionRow()
            action_row.set_title(language)
            action_row.set_activatable(True)

            switch = Gtk.Switch.new()
            switch.set_valign(Gtk.Align.CENTER)
            switch.set_halign(Gtk.Align.CENTER)
            switch.set_active(code in servers_languages)
            switch.connect('notify::active', self.on_language_activated, code)
            action_row.add_suffix(switch)
            action_row.set_activatable_widget(switch)

            self.parent.servers_languages_subpage_group.add(action_row)

    def on_language_activated(self, switch_button, _gparam, code):
        if switch_button.get_active():
            self.settings.add_servers_language(code)
        else:
            self.settings.remove_servers_language(code)

    def present(self, _widget):
        self.parent.subtitle_label.set_text(_('Servers Languages'))
        self.parent.subpages_stack.set_visible_child_name('servers_languages')
        self.parent.set_visible_child_name('subpages')


class PreferencesServersSettingsSubpage:
    parent = NotImplemented
    settings = NotImplemented

    def __init__(self, parent):
        self.parent = parent
        self.settings = Settings.get_default()
        self.keyring_helper = KeyringHelper()

        settings = self.settings.servers_settings
        languages = self.settings.servers_languages
        credentials_storage_plaintext_fallback = self.settings.credentials_storage_plaintext_fallback

        servers_data = {}
        for server_data in get_servers_list(order_by=('name', 'lang')):
            main_id = get_server_main_id_by_id(server_data['id'])

            if main_id not in servers_data:
                servers_data[main_id] = dict(
                    main_id=main_id,
                    name=server_data['name'],
                    module=server_data['module'],
                    langs=[],
                )

            if not languages or server_data['lang'] in languages:
                servers_data[main_id]['langs'].append(server_data['lang'])

        for server_main_id, server_data in servers_data.items():
            if not server_data['langs']:
                continue

            server_class = getattr(server_data['module'], server_data['main_id'].capitalize())
            has_login = getattr(server_class, 'has_login')

            server_settings = settings.get(server_main_id)
            server_enabled = server_settings is None or server_settings['enabled'] is True

            if len(server_data['langs']) > 1 or has_login:
                vbox = Gtk.Box(
                    orientation=Gtk.Orientation.VERTICAL,
                    margin_start=12, margin_top=6, margin_end=12, margin_bottom=6,
                    spacing=12
                )

                expander_row = Adw.ExpanderRow()
                expander_row.set_title(server_data['name'])
                expander_row.set_enable_expansion(server_enabled)
                expander_row.connect('notify::enable-expansion', self.on_server_activated, server_main_id)
                expander_row.add(vbox)

                self.parent.servers_settings_subpage_group.add(expander_row)

                if len(server_data['langs']) > 1:
                    for lang in server_data['langs']:
                        lang_enabled = server_settings is None or server_settings['langs'].get(lang, True)

                        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, margin_top=6, margin_bottom=6, spacing=12)

                        label = Gtk.Label(label=LANGUAGES[lang], xalign=0, hexpand=True)
                        hbox.append(label)

                        switch = Gtk.Switch.new()
                        switch.set_active(lang_enabled)
                        switch.connect('notify::active', self.on_server_language_activated, server_main_id, lang)
                        hbox.append(switch)

                        vbox.append(hbox)

                if has_login:
                    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, margin_top=12, margin_bottom=12, spacing=12)
                    vbox.append(box)

                    label = Gtk.Label(label=_('User Account'))
                    label.set_valign(Gtk.Align.CENTER)
                    box.append(label)

                    if server_class.base_url is None:
                        # Server has a customizable address/base_url (ex. Komga)
                        address_entry = Gtk.Entry()
                        address_entry.set_icon_from_icon_name(Gtk.EntryIconPosition.PRIMARY, 'network-server-symbolic')
                        box.append(address_entry)
                    else:
                        address_entry = None

                    entry_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
                    entry_box.append(Gtk.Image.new_from_icon_name('avatar-default-symbolic'))
                    username_entry = Gtk.Entry(hexpand=True)
                    entry_box.append(username_entry)
                    box.append(entry_box)

                    entry_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
                    entry_box.append(Gtk.Image.new_from_icon_name('dialog-password-symbolic'))
                    password_entry = Gtk.PasswordEntry(hexpand=True)
                    password_entry.set_show_peek_icon(True)
                    entry_box.append(password_entry)
                    box.append(entry_box)

                    plaintext_checkbutton = None
                    if self.keyring_helper.is_disabled or not self.keyring_helper.has_recommended_backend:
                        label = Gtk.Label()
                        label.set_line_wrap(True)
                        if self.keyring_helper.is_disabled:
                            label.add_css_class('dim-label')
                            label.set_text(_('System keyring service is disabled. Credential cannot be saved.'))
                            box.append(label)
                        elif not self.keyring_helper.has_recommended_backend:
                            if not credentials_storage_plaintext_fallback:
                                plaintext_checkbutton = Gtk.CheckButton.new()
                                label.set_text(_('No keyring backends were found to store credential. Use plaintext storage as fallback.'))
                                plaintext_checkbutton.add(label)
                                box.append(plaintext_checkbutton)
                            else:
                                label.add_css_class('dim-label')
                                label.set_text(_('No keyring backends were found to store credential. Plaintext storage will be used as fallback.'))
                                box.append(label)

                    btn = Gtk.Button()
                    btn_hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
                    btn_hbox.set_halign(Gtk.Align.CENTER)
                    btn.icon = Gtk.Image(visible=False)
                    btn_hbox.append(btn.icon)
                    btn_hbox.append(Gtk.Label(label=_('Test')))
                    btn.connect(
                        'clicked', self.save_credential,
                        server_main_id, server_class, username_entry, password_entry, address_entry, plaintext_checkbutton
                    )
                    btn.set_child(btn_hbox)
                    box.append(btn)

                    credential = self.keyring_helper.get(server_main_id)
                    if credential:
                        if address_entry is not None:
                            address_entry.set_text(credential.address)
                        username_entry.set_text(credential.username)
                        password_entry.set_text(credential.password)
            else:
                action_row = Adw.ActionRow()
                action_row.set_title(server_data['name'])

                switch = Gtk.Switch.new()
                switch.set_active(server_enabled)
                switch.set_valign(Gtk.Align.CENTER)
                switch.set_halign(Gtk.Align.CENTER)
                switch.connect('notify::active', self.on_server_activated, server_main_id)
                action_row.set_activatable_widget(switch)
                action_row.add_suffix(switch)

                self.parent.servers_settings_subpage_group.add(action_row)

    def on_server_activated(self, widget, _gparam, server_main_id):
        if isinstance(widget, Adw.ExpanderRow):
            self.settings.toggle_server(server_main_id, widget.get_enable_expansion())
        else:
            self.settings.toggle_server(server_main_id, widget.get_active())

    def on_server_language_activated(self, switch_button, _gparam, server_main_id, lang):
        self.settings.toggle_server_lang(server_main_id, lang, switch_button.get_active())

    def present(self, _widget):
        self.parent.subtitle_label.set_text(_('Servers Settings'))
        self.parent.subpages_stack.set_visible_child_name('servers_settings')
        self.parent.set_visible_child_name('subpages')

    def save_credential(self, button, server_main_id, server_class, username_entry, password_entry, address_entry, plaintext_checkbutton):
        username = username_entry.get_text()
        password = password_entry.get_text()
        if address_entry is not None:
            address = address_entry.get_text().strip()
            if not address.startswith(('http://', 'https://')):
                return

            server = server_class(username=username, password=password, address=address)
        else:
            address = None
            server = server_class(username=username, password=password)

        button.icon.show()
        if server.logged_in:
            button.icon.set_from_icon_name('object-select-symbolic')
            if self.keyring_helper.is_disabled or plaintext_checkbutton is not None and not plaintext_checkbutton.get_active():
                return

            if plaintext_checkbutton is not None and plaintext_checkbutton.get_active():
                # Save user agrees to save credentials in plaintext
                self.parent.credentials_storage_plaintext_fallback_switch.set_active(True)

            self.keyring_helper.store(server_main_id, username, password, address)
        else:
            button.icon.set_from_icon_name('computer-fail-symbolic')
