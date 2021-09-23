# Copyright (C) 2019-2021 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-only or GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from .utils import *

from bs4 import BeautifulSoup
from functools import cached_property
from functools import lru_cache
import gi
import importlib
import inspect
import logging
from operator import itemgetter
import os
import pickle
from PIL import Image
import pkgutil
import requests
from requests.adapters import TimeoutSauce
import struct
from sys import meta_path

gi.require_version('Gtk', '3.0')
gi.require_version('WebKit2', '4.0')

from gi.repository import GLib
from gi.repository import Gtk
from gi.repository import WebKit2

from komikku.utils import get_cache_dir
from komikku.utils import KeyringHelper

# https://www.localeplanet.com/icu/
LANGUAGES = dict(
    ar='العربية',
    id='Bahasa Indonesia',
    cs='Čeština',
    de='Deutsch',
    en='English',
    es='Español',
    fr='Français',
    it='Italiano',
    nl='Nederlands',
    nb='Norsk Bokmål',
    pl='Polski',
    pt='Português',
    pt_BR='Português (Brasil)',
    ru='Русский',
    vi='Tiếng Việt',
    tr='Türkçe',
    ja='日本語',
    ko='한국어',
    th='ไทย',
    zh_Hans='中文 (简体)',
    zh_Hant='中文 (繁體)',
)

REQUESTS_TIMEOUT = 5

SERVERS_PATH = os.environ.get('KOMIKKU_SERVERS_PATH')

USER_AGENT = 'Mozilla/5.0 (X11; Linux x86_64; rv:86.0) Gecko/20100101 Firefox/86.0'
USER_AGENT_MOBILE = 'Mozilla/5.0 (Linux; U; Android 4.1.1; en-gb; Build/KLP) AppleWebKit/534.30 (KHTML, like Gecko) Version/4.0 Safari/534.30'

VERSION = 1

logger = logging.getLogger('komikku.servers')


class KomikkuServerFinder(importlib.abc.MetaPathFinder):

    def __init__(self):
        servers_path_env = os.environ.get('KOMIKKU_SERVERS_PATH')
        self._prefix = 'komikku.servers.'
        if servers_path_env:
            self._servers_path = servers_path_env.split(os.pathsep)
        else:
            self._servers_path = []

    def find_spec(self, fullname, path, target=None):
        if fullname.startswith(self._prefix):
            shortname = fullname[len(self._prefix):]
            filename_base = shortname.replace('.', '/')
            for servers_path in self._servers_path:
                candidate1 = os.path.join(servers_path, filename_base) + '.py'
                candidate2 = os.path.join(servers_path, filename_base, '__init__.py')
                if os.path.exists(candidate1):
                    return self._module_spec(fullname, candidate1)
                if os.path.exists(candidate2):
                    return self._module_spec(fullname, candidate2)

    def _module_spec(self, fullname, filename):
        return importlib.machinery.ModuleSpec(
            fullname,
            KomikkuServerLoader(fullname, filename),
            origin=filename,
        )


class KomikkuServerLoader(importlib.machinery.SourceFileLoader):

    def create_module(self, spec):
        # Compare and contrast _new_module in importlib._bootstrap
        # We set the file name early, because we only load real files anyway,
        # see KomikkuServerFinder.find_spec, and because it helps locating
        # relative files, such as logos.
        module = type(importlib)(spec.name)
        module.__file__ = spec.origin
        return module


meta_path.append(KomikkuServerFinder())


class CustomTimeout(TimeoutSauce):
    def __init__(self, *args, **kwargs):
        if kwargs['connect'] is None:
            kwargs['connect'] = REQUESTS_TIMEOUT
        if kwargs['read'] is None:
            kwargs['read'] = REQUESTS_TIMEOUT * 3
        super().__init__(*args, **kwargs)


# Set requests timeout globally, instead of specifying ``timeout=..`` kwarg on each call
requests.adapters.TimeoutSauce = CustomTimeout


class HeadlessBrowser(Gtk.Window):
    lock = False

    def __init__(self, *args, **kwargs):
        self.__handlers_ids = []
        self.debug = kwargs.pop('debug', False)

        super().__init__(*args, **kwargs)

        self.scrolledwindow = Gtk.ScrolledWindow()
        self.scrolledwindow.get_hscrollbar().hide()
        self.scrolledwindow.get_vscrollbar().hide()

        self.viewport = Gtk.Viewport()
        self.scrolledwindow.add(self.viewport)
        self.add(self.scrolledwindow)

        self.webview = WebKit2.WebView()
        self.viewport.add(self.webview)

        self.settings = self.webview.get_settings()
        self.settings.set_enable_dns_prefetching(True)
        self.settings.set_enable_page_cache(False)
        # self.settings.props.enable_developer_extras = True

        self.web_context = self.webview.get_context()
        self.web_context.set_cache_model(WebKit2.CacheModel.DOCUMENT_VIEWER)

        if not self.debug:
            # Make window almost invisible (part 1)
            self.set_decorated(False)
            self.set_focus_on_map(False)
            self.resize(1, 1)

    def close(self, blank=True):
        logger.debug('WebKit2 | Closed')

        self.disconnect_all_signals()

        if blank:
            GLib.idle_add(self.webview.load_uri, 'about:blank')
        self.hide()

        self.lock = False

    def connect_signal(self, *args):
        handler_id = self.webview.connect(*args)
        self.__handlers_ids.append(handler_id)

    def disconnect_all_signals(self):
        for handler_id in self.__handlers_ids:
            self.webview.disconnect(handler_id)

        self.__handlers_ids = []

    def open(self, uri, user_agent=None, settings=None):
        if self.lock:
            return False

        self.settings.set_user_agent(user_agent or USER_AGENT)
        self.settings.set_auto_load_images(True if not settings or settings.get('auto_load_images', True) else False)

        self.lock = True

        logger.debug('WebKit2 | Load page %s', uri)

        def do_load():
            self.show_all()

            if not self.debug:
                # Make window almost invisible (part 2)
                self.set_keep_below(True)
                self.iconify()

            self.webview.load_uri(uri)

        GLib.idle_add(do_load)

        return True


headless_browser = HeadlessBrowser(debug=False)


class Server:
    id: str
    name: str
    lang: str

    has_login = False
    headers = None
    is_nsfw = False
    logged_in = False
    long_strip_genres = []
    manga_title_css_selector = None  # Used to extract manga title in a manga URL
    session_expiration_cookies = []  # Session cookies for which validity (not expired) must be checked
    status = 'enabled'
    sync = False

    base_url = None

    __sessions = {}  # to cache all existing sessions

    @classmethod
    def get_manga_initial_data_from_url(cls, url):
        if cls.manga_title_css_selector:
            c = cls()
            r = c.session_get(url)
            if r.status_code != 200:
                return None

            soup = BeautifulSoup(r.content, 'html.parser')

            title_element = soup.select_one(cls.manga_title_css_selector)
            if not title_element:
                return None

            results = c.search(title_element.text.strip())
            if not results:
                return None

            slug = results[0]['slug']
        else:
            slug = url.split('?')[0].split('/')[-1]

        return dict(slug=slug)

    def do_login(self, username=None, password=None):
        if username and password:
            # Username and password are provided only when user defines the credentials in the settings
            self.clear_session()
        elif credential := KeyringHelper().get(get_server_main_id_by_id(self.id)):
            if self.base_url is None:
                self.base_url = credential.address

        if self.session is None:
            if self.load_session():
                self.logged_in = True
            else:
                self.session = requests.Session()
                if self.headers:
                    self.session.headers = self.headers

                if username is None and password is None:
                    if credential:
                        self.logged_in = self.login(credential.username, credential.password)
                else:
                    self.logged_in = self.login(username, password)
        else:
            self.logged_in = True

    def login(self, username, password):
        return False

    @cached_property
    def logo_path(self):
        module_path = os.path.dirname(os.path.abspath(inspect.getfile(self.__class__)))

        path = os.path.join(module_path, get_server_main_id_by_id(self.id) + '.ico')
        if not os.path.exists(path):
            return None

        return path

    @property
    def session(self):
        return Server.__sessions.get(self.id)

    @session.setter
    def session(self, value):
        Server.__sessions[self.id] = value

    @property
    def sessions_dir(self):
        dir = os.path.join(get_cache_dir(), 'sessions')
        if not os.path.exists(dir):
            os.mkdir(dir)

        return dir

    def clear_session(self, all=False):
        main_id = get_server_main_id_by_id(self.id)

        # Remove session from disk
        file_path = os.path.join(self.sessions_dir, '{0}.pickle'.format(main_id))
        if os.path.exists(file_path):
            os.unlink(file_path)

        if all:
            for id in Server.__sessions.copy():
                if id.startswith(main_id):
                    del Server.__sessions[id]
        elif self.id in Server.__sessions:
            del Server.__sessions[self.id]

    def get_manga_cover_image(self, url):
        """
        Returns manga cover (image) content
        """
        if url is None:
            return None

        r = self.session_get(url, headers={'Referer': self.base_url})
        if r is None:
            return None

        if r.status_code != 200:
            return None

        buffer = r.content
        mime_type = get_buffer_mime_type(buffer)

        if not mime_type.startswith('image'):
            return None

        if mime_type == 'image/webp':
            buffer = convert_image(buffer, ret_type='bytes')

        return buffer

    def is_long_strip(self, data):
        """
        Returns True if the manga is a long strip, False otherwise.

        The server shall not modify `data` to form the return value.
        """
        if not self.long_strip_genres:
            return False

        for genre in data['genres']:
            if genre in self.long_strip_genres:
                return True

        return False

    def load_session(self):
        """ Load session from disk """

        file_path = os.path.join(self.sessions_dir, '{0}.pickle'.format(get_server_main_id_by_id(self.id)))
        if not os.path.exists(file_path):
            return False

        with open(file_path, 'rb') as f:
            session = pickle.load(f)

        # Check session validity
        if self.session_expiration_cookies:
            # One or more cookies for which the expiration date must be checked are defined
            # If one of them has expired, session must be cleared
            for cookie in session.cookies:
                if cookie.name not in self.session_expiration_cookies:
                    continue

                if cookie.is_expired():
                    self.clear_session(all=True)
                    return False

        self.session = session

        return True

    def save_session(self):
        """ Save session to disk """

        file_path = os.path.join(self.sessions_dir, '{0}.pickle'.format(get_server_main_id_by_id(self.id)))
        with open(file_path, 'wb') as f:
            pickle.dump(self.session, f)

    def session_get(self, *args, **kwargs):
        try:
            r = self.session.get(*args, **kwargs)
        except Exception:
            raise

        return r

    def session_patch(self, *args, **kwargs):
        try:
            r = self.session.patch(*args, **kwargs)
        except Exception:
            raise

        return r

    def session_post(self, *args, **kwargs):
        try:
            r = self.session.post(*args, **kwargs)
        except Exception:
            raise

        return r

    def update_chapter_read_progress(self, data, manga_slug, manga_name, chapter_slug, chapter_url):
        return NotImplemented


@lru_cache(maxsize=None)
def get_servers_list(include_disabled=False, order_by=('lang', 'name')):
    def iter_namespace(ns_pkg):
        # Specifying the second argument (prefix) to iter_modules makes the
        # returned name an absolute name instead of a relative one. This allows
        # import_module to work without having to do additional modification to
        # the name.
        return pkgutil.iter_modules(ns_pkg.__path__, ns_pkg.__name__ + '.')

    modules = []
    if SERVERS_PATH:
        # Load servers from extermal folders defined in KOMIKKU_SERVERS_PATH environment variable
        for servers_path in SERVERS_PATH.split(os.pathsep):
            servers_path = os.path.abspath(servers_path)
            if not os.path.exists(servers_path):
                continue

            count = 0
            for path, _dirs, _files in os.walk(servers_path):
                relpath = path[len(servers_path):]
                if not relpath or relpath == 'multi':
                    continue

                modules.append(importlib.import_module(relpath.replace('/', '.'),
                                                       package='komikku.servers'))
                count += 1

            logger.info('Load {0} servers from external folder: {1}'.format(count, servers_path))
    else:
        import komikku.servers

        for _finder, name, _ispkg in iter_namespace(komikku.servers):
            modules.append(importlib.import_module(name))

    servers = []
    for module in modules:
        for _name, obj in dict(inspect.getmembers(module)).items():
            if not hasattr(obj, 'id') or not hasattr(obj, 'name') or not hasattr(obj, 'lang'):
                continue
            if NotImplemented in (obj.id, obj.name, obj.lang):
                continue

            if not include_disabled and obj.status == 'disabled':
                continue

            if inspect.isclass(obj):
                logo_path = os.path.join(os.path.dirname(os.path.abspath(module.__file__)), get_server_main_id_by_id(obj.id) + '.ico')

                servers.append(dict(
                    id=obj.id,
                    name=obj.name,
                    lang=obj.lang,
                    has_login=obj.has_login,
                    is_nsfw=obj.is_nsfw,
                    class_name=get_server_class_name_by_id(obj.id),
                    logo_path=logo_path if os.path.exists(logo_path) else None,
                    module=module,
                ))

    return sorted(servers, key=itemgetter(*order_by))


def get_allowed_servers_list(settings):
    servers_settings = settings.servers_settings
    servers_languages = settings.servers_languages

    servers = []
    for server_data in get_servers_list():
        if servers_languages and server_data['lang'] not in servers_languages:
            continue

        server_settings = servers_settings.get(get_server_main_id_by_id(server_data['id']))
        if server_settings is not None and (not server_settings['enabled'] or server_settings['langs'].get(server_data['lang']) is False):
            continue

        if settings.nsfw_content is False and server_data['is_nsfw']:
            continue

        servers.append(server_data)

    return servers


def search_duckduckgo(site, term):
    session = requests.Session()
    session.headers.update({'user-agent': USER_AGENT})

    params = dict(
        kd=-1,
        q=f'site:{site} {term}',
    )

    try:
        r = session.get('https://duckduckgo.com/lite', params=params)
    except Exception:
        raise

    soup = BeautifulSoup(r.content, 'html.parser')

    results = []
    for a_element in soup.find_all('a', class_='result-link'):
        results.append(dict(
            name=a_element.text.strip(),
            url=a_element.get('href'),
        ))

    return results
