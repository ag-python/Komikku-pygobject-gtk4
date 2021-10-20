# -*- coding: utf-8 -*-

# Copyright (C) 2019-2021 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-only or GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from komikku.servers import SERVERS_PATH
if SERVERS_PATH:
    # External module
    from multi.genkan import Genkan
else:
    from komikku.servers.multi.genkan import Genkan


class Zeroscans(Genkan):
    id = 'zeroscans'
    name = 'Zero Scans'
    lang = 'en'

    base_url = 'https://zeroscans.com'
    search_url = base_url + '/comics?query={0}'
    most_populars_url = base_url + '/home'
    manga_url = base_url + '/comics/{0}'
    chapter_url = base_url + '/comics/{0}/{1}'
    image_url = base_url + '{0}'
