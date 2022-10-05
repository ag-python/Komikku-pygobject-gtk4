# -*- coding: utf-8 -*-

# Copyright (C) 2019-2021 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-only or GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from komikku.servers.multi.my_manga_reader_cms import MyMangaReaderCMS


class Scanop(MyMangaReaderCMS):
    id = 'scanop'
    name = 'Scan OP'
    lang = 'fr'
    status = 'disabled'

    base_url = 'https://scan-op.cc'
    search_url = base_url + '/search'
    most_populars_url = base_url + '/filterList?page=1&sortBy=views&asc=false'
    manga_url = base_url + '/manga/{0}'
    chapter_url = base_url + '/manga/{0}/{1}'
    image_url = None  # Images URLs can't be computed with manga/chapter/image slugs
    cover_url = base_url + '/uploads/manga/{0}/cover/cover_250x350.jpg'
