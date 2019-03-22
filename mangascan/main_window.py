from gi.repository import Gio
from gi.repository import Gdk
from gi.repository import Gtk
from gi.repository.GdkPixbuf import Pixbuf

from mangascan.add_dialog import AddDialog
import mangascan.config_manager
from mangascan.settings_dialog import SettingsDialog
from mangascan.model import create_db_connection
from mangascan.model import Manga
from mangascan.reader import Reader


class MainWindow(Gtk.ApplicationWindow):
    mobile_width = False
    page = 'library'
    manga = None
    reader = None
    first_start_grid = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.logging_manager = kwargs['application'].get_logger()

        self.builder = Gtk.Builder()
        self.builder.add_from_resource("/com/gitlab/valos/MangaScan/main_window.ui")
        self.stack = self.builder.get_object('stack')
        self.reader = Reader(self.builder)

        self.assemble_window()

        if Gio.Application.get_default().development_mode is True:
            mangascan.config_manager.set_development_backup_mode(True)

    def add_actions(self):
        add_action = Gio.SimpleAction.new("add", None)
        add_action.connect("activate", self.on_left_button_clicked)

        delete_action = Gio.SimpleAction.new("delete", None)
        delete_action.connect("activate", self.on_delete_menu_clicked)

        settings_action = Gio.SimpleAction.new("settings", None)
        settings_action.connect("activate", self.on_settings_menu_clicked)

        about_action = Gio.SimpleAction.new("about", None)
        about_action.connect("activate", self.on_about_menu_clicked)

        shortcuts_action = Gio.SimpleAction.new("shortcuts", None)
        shortcuts_action.connect("activate", self.on_shortcuts_menu_clicked)

        self.application.add_action(add_action)
        self.application.add_action(delete_action)
        self.application.add_action(settings_action)
        self.application.add_action(about_action)
        self.application.add_action(shortcuts_action)

    def add_global_accelerators(self):
        self.application.set_accels_for_action("app.settings", ["<Control>p"])
        self.application.set_accels_for_action("app.add", ["<Control>plus"])

    def assemble_window(self):
        window_size = mangascan.config_manager.get_window_size()
        self.set_default_size(window_size[0], window_size[1])

        # Titlebar
        self.titlebar = self.builder.get_object("titlebar")
        self.headerbar = self.builder.get_object('headerbar')

        self.left_button = self.builder.get_object("left_button")
        self.left_button.connect("clicked", self.on_left_button_clicked, None)
        self.left_button_stack = self.builder.get_object("left_button_stack")

        self.set_titlebar(self.titlebar)

        # Fisrt start grid
        self.first_start_grid = self.builder.get_object("first_start_grid")
        pix = Pixbuf.new_from_resource_at_scale("/com/gitlab/valos/MangaScan/images/logo.png", 256, 256, True)
        app_logo = self.builder.get_object("app_logo")
        app_logo.set_from_pixbuf(pix)

        # Library
        self.library_flowbox = self.builder.get_object('library_page_flowbox')
        self.library_flowbox.connect("child-activated", self.on_manga_clicked)
        self.library_flowbox.set_sort_func(self.sort_library)

        self.populate_library_page()

        # Window
        self.connect("delete-event", self.on_application_quit)
        self.connect("check-resize", self.responsive_listener)

        # Custom CSS
        screen = Gdk.Screen.get_default()

        css_provider = Gtk.CssProvider()
        css_provider_resource = Gio.File.new_for_uri("resource:///com/gitlab/valos/MangaScan/css/style.css")
        css_provider.load_from_file(css_provider_resource)

        context = Gtk.StyleContext()
        context.add_provider_for_screen(screen, css_provider, Gtk.STYLE_PROVIDER_PRIORITY_USER)
        if Gio.Application.get_default().development_mode is True:
            context.add_class("devel")

        # Apply theme
        gtk_settings = Gtk.Settings.get_default()
        gtk_settings.set_property("gtk-application-prefer-dark-theme", mangascan.config_manager.get_dark_theme())

        self.show_all()

    def change_layout(self):
        pass

    def insert_manga_into_library_flowbox(self, manga, position=-1):
        cover_image = Gtk.Image()
        pixbuf = Pixbuf.new_from_file_at_scale(manga.cover_path, 180, -1, True)
        cover_image.set_from_pixbuf(pixbuf)
        cover_image.manga = manga
        cover_image.show()

        self.library_flowbox.insert(cover_image, position)

    def on_about_menu_clicked(self, action, param):
        builder = Gtk.Builder()
        builder.add_from_resource("/com/gitlab/valos/MangaScan/about_dialog.ui")

        about_dialog = builder.get_object("about_dialog")
        about_dialog.set_modal(True)
        about_dialog.set_transient_for(self)
        about_dialog.present()

    def on_application_quit(self, window, event):
        self.save_window_size()

    def on_chapter_clicked(self, listbox, row):
        self.reader.init(row.chapter)

        self.show_page('reader')

    def on_delete_menu_clicked(self, action, param):
        db_conn = create_db_connection()
        nb_mangas = db_conn.execute('SELECT count(*) FROM mangas').fetchone()[0]
        db_conn.close()

        if nb_mangas == 1:
            self.manga.delete()

            # Library is now empty
            self.remove(self.stack)
            self.populate_library_page()
        else:
            # Remove manga cover in library flowbox
            for child in self.library_flowbox.get_children():
                if child.get_children()[0].manga == self.manga:
                    child.destroy()
                    break

            self.manga.delete()

        self.show_page('library')

    def on_left_button_clicked(self, action, param):
        if self.page == 'library':
            AddDialog(self).open(action, param)
        elif self.page == 'manga':
            # Invalidate sort to trigger library flowbox sort function
            self.library_flowbox.invalidate_sort()
            self.show_page('library')
        elif self.page == 'reader':
            self.populate_manga_page()
            self.show_page('manga')

    def on_manga_added(self, manga):
        """
        Called from 'Add dialog' when user clicks on + button
        """
        db_conn = create_db_connection()
        nb_mangas = db_conn.execute('SELECT count(*) FROM mangas').fetchone()[0]
        db_conn.close()

        if nb_mangas == 1:
            # Library was previously empty
            self.remove(self.first_start_grid)
            self.populate_library_page()
        else:
            self.insert_manga_into_library_flowbox(manga)

    def on_manga_clicked(self, flowbox, child):
        self.manga = child.get_children()[0].manga

        self.populate_manga_page()

        self.show_page('manga')

    def on_settings_menu_clicked(self, action, param):
        SettingsDialog(self).open(action, param)

    def on_shortcuts_menu_clicked(self, action, param):
        builder = Gtk.Builder()
        builder.add_from_resource("/com/gitlab/valos/MangaScan/shortcuts_overview.ui")

        shortcuts_overview = builder.get_object("shortcuts_overview")
        shortcuts_overview.set_modal(True)
        shortcuts_overview.set_transient_for(self)
        shortcuts_overview.present()

    def populate_library_page(self):
        db_conn = create_db_connection()
        mangas_rows = db_conn.execute('SELECT * FROM mangas ORDER BY last_read DESC').fetchall()

        if len(mangas_rows) == 0:
            # Display first start message
            self.add(self.first_start_grid)
            return

        self.add(self.stack)

        # Clear library flowbox
        for child in self.library_flowbox.get_children():
            self.library_flowbox.remove(child)
            child.destroy()

        # Populate flowbox with mangas covers
        for row in mangas_rows:
            self.insert_manga_into_library_flowbox(Manga(row['id']))

        db_conn.close()

        self.library_flowbox.show_all()

    def populate_manga_page(self):
        pixbuf = Pixbuf.new_from_file_at_scale(self.manga.cover_path, 180, -1, True)
        self.builder.get_object('cover_image').set_from_pixbuf(pixbuf)

        self.builder.get_object('author_value_label').set_text(self.manga.author or '-')
        self.builder.get_object('type_value_label').set_text(self.manga.types or '-')
        self.builder.get_object('status_value_label').set_text(self.manga.status or '-')
        self.builder.get_object('server_value_label').set_text(
            '{0} ({1} chapters)'.format(self.manga.server.name, len(self.manga.chapters)))

        self.builder.get_object('synopsis_value_label').set_text(self.manga.synopsis or '-')

        listbox = self.builder.get_object('chapters_listbox')
        listbox.connect("row-activated", self.on_chapter_clicked)

        for child in listbox.get_children():
            child.destroy()

        for chapter in self.manga.chapters:
            row = Gtk.ListBoxRow()
            row.get_style_context().add_class('listboxrow-chapter')
            row.chapter = chapter
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            row.add(box)

            # Chapter title
            label = Gtk.Label(xalign=0)
            label.set_line_wrap(True)
            label.set_text(chapter.title)
            box.pack_start(label, True, True, 0)

            # Nb read / Nb pages
            label = Gtk.Label(xalign=0)
            if chapter.pages is not None:
                label.set_text('{0}/{1}'.format(chapter.last_page_read_index + 1, len(chapter.pages.split(','))))
            box.pack_start(label, True, True, 0)

            listbox.add(row)

        listbox.show_all()

    def responsive_listener(self, window):
        if self.get_allocation().width < 700:
            if self.mobile_width is True:
                return

            self.mobile_width = True
            self.change_layout()
        else:
            if self.mobile_width is True:
                self.mobile_width = False
                self.change_layout()

    def save_window_size(self):
        window_size = [self.get_size().width, self.get_size().height]
        mangascan.config_manager.set_window_size(window_size)

    def show_page(self, name):
        if name == 'library':
            self.headerbar.set_title('Manga Scan')
            self.builder.get_object('menubutton').set_popover(self.builder.get_object('menubutton_popover'))
        elif name == 'manga':
            self.headerbar.set_title(self.manga.name)
            self.builder.get_object('menubutton').set_popover(self.builder.get_object('manga_page_menubutton_popover'))
        elif name == 'reader':
            pass

        self.left_button_stack.set_visible_child_name(name)
        self.stack.set_visible_child_name(name)
        self.page = name

    def sort_library(self, child1, child2):
        manga1 = child1.get_children()[0].manga
        manga2 = child2.get_children()[0].manga

        # TODO: improve me
        if manga1.last_read is not None and manga2.last_read is not None:
            if manga1.last_read > manga2.last_read:
                return -1
            elif manga1.last_read < manga2.last_read:
                return 1
            else:
                return 0

        if manga1.last_read:
            return -1
        else:
            return 1
