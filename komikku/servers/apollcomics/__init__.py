# -*- coding: utf-8 -*-

# Copyright (C) 2019-2021 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-only or GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from komikku.servers import SERVERS_PATH
if SERVERS_PATH:
    # External module
    from multi.madara import Madara
else:
    from komikku.servers.multi.madara import Madara


class Apollcomics(Madara):
    id = 'apollcomics'
    name = 'Apoll Comics'
    lang = 'es'

    base_url = 'https://apollcomics.xyz/'
