# Copyright (C) 2019-2022 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-only or GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from gettext import gettext as _

from gi.repository import Gdk
from gi.repository import GLib
from gi.repository import GObject
from gi.repository import Gtk

from komikku.reader.pager import BasePager
from komikku.reader.pager.page import Page


class WebtoonPager(Gtk.ScrolledWindow, BasePager):
    """Vertical smooth/continuous scrolling (a.k.a. infinite canvas) pager"""

    _interactive = False
    current_chapter_id = None
    current_page = None
    current_page_scroll_value = 0
    nb_preloaded_pages = 1  # Number of preloaded pages before and after the center/visible page
    scroll_direction = None
    clamp_size = 800

    ignore_scroll_value_changes = False

    def __init__(self, reader):
        Gtk.ScrolledWindow.__init__(self)
        BasePager.__init__(self, reader)

        self.get_hscrollbar().hide()
        self.get_vscrollbar().hide()
        self.set_kinetic_scrolling(False)

        self.vadj = self.get_vadjustment()

        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.START)
        self.set_child(self.box)

        self.controller_scroll = Gtk.EventControllerScroll.new(Gtk.EventControllerScrollFlags.VERTICAL)
        self.controller_scroll.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        self.add_controller(self.controller_scroll)
        self.controller_scroll.connect('scroll', self.on_scroll)

        self.vadj.connect('notify::upper', self.on_scroll_upper_changed)

        self.zoom['active'] = False

    @GObject.Property(type=bool, default=False)
    def interactive(self):
        return self._interactive

    @interactive.setter
    def interactive(self, value):
        self._interactive = value

    @property
    def pages(self):
        children = []
        for page in self.box:
            children.append(page)

        return children

    @property
    def pages_offsets(self):
        pages = self.pages

        offsets = [0]
        for index, page in enumerate(pages[:-1]):
            prev = offsets[index]
            _minimal, natural = page.get_preferred_size()
            offsets.append(prev + natural.height)

        return offsets

    def add_page(self, position):
        pages = self.pages
        if position == Gtk.PositionType.TOP:
            page = pages[0]
        else:
            page = pages[-1]

        if not page.loadable and page.error is None:
            # Loop until page is loadable or page is on error
            return GLib.SOURCE_CONTINUE

        if not page.loadable:
            print('page unknown')
            return GLib.SOURCE_REMOVE

        if position == Gtk.PositionType.TOP:
            pages[-1].clean()
            self.box.remove(pages[-1])

            new_page = Page(self, page.chapter, page.index - 1)
            self.box.prepend(new_page)
        else:
            pages[0].clean()
            self.box.remove(pages[0])

            new_page = Page(self, page.chapter, page.index + 1)
            self.box.append(new_page)

        self.adjust_scroll()

        new_page.connect('notify::status', self.on_page_status_changed)
        new_page.connect('rendered', self.on_page_rendered)
        new_page.render()

        return GLib.SOURCE_REMOVE

    def adjust_scroll(self, value=None, emit_signal=True):
        if value is None:
            value = self.get_page_offset(self.current_page) + self.current_page_scroll_value

        self.vadj.set_value(value)

    def clear(self):
        page = self.box.get_first_child()
        while page:
            next_page = page.get_next_sibling()
            page.clean()
            self.box.remove(page)
            page = next_page

    def dispose(self):
        BasePager.dispose(self)
        self.clear()

    def get_page_offset(self, page):
        offset = 0
        for p in self.box:
            if p == page:
                break
            _minimal, natural = p.get_preferred_size()
            offset += natural.height

        return offset

    def get_position(self, scroll_value):
        pages_offsets = self.pages_offsets
        position = None

        for i, page_offset in enumerate(reversed(pages_offsets)):
            if scroll_value >= page_offset:
                position = len(pages_offsets) - 1 - i
                break

        return position

    def goto_page(self, index):
        self.init(self.current_page.chapter, index)

    def init(self, chapter, page_index=None):
        self.clear()

        if page_index is None:
            if chapter.read:
                page_index = 0
            elif chapter.last_page_read_index is not None:
                page_index = chapter.last_page_read_index
            else:
                page_index = 0

        for i in range(-self.nb_preloaded_pages, self.nb_preloaded_pages + 1):
            page = Page(self, chapter, page_index + i)
            page.connect('notify::status', self.on_page_status_changed)
            page.connect('rendered', self.on_page_rendered)
            self.box.append(page)
            if i == 0:
                self.current_page = page
                page.render()

        def render_pages():
            pages = self.pages
            n_pages = len(pages)
            if self.scroll_direction == Gtk.DirectionType.DOWN:
                pages = reversed(pages)

            done = 0
            for page in pages:
                if page.status is None:
                    page.render()
                else:
                    done += 1

            self.adjust_scroll()

            return True if done < n_pages else False

        GLib.timeout_add(1000, render_pages)
        GLib.idle_add(self.update, self.current_page)

    def on_btn_clicked(self, _gesture, _n_press, x, y):
        if not self.interactive:
            return

        self.on_single_click(x, y)

        return Gdk.EVENT_STOP

    def on_key_pressed(self, _controller, keyval, _keycode, state):
        if self.window.page != 'reader' or not self.interactive:
            return Gdk.EVENT_PROPAGATE

        modifiers = Gtk.accelerator_get_default_mod_mask()
        if (state & modifiers) != 0:
            return Gdk.EVENT_PROPAGATE

        if keyval in (Gdk.KEY_Down, Gdk.KEY_KP_Down):
            self.hide_cursor()
            self.scroll_direction = Gtk.DirectionType.DOWN
            self.ignore_scroll_value_changes = False
            self.vadj.set_value(self.vadj.get_value() + self.vadj.get_step_increment())
            return Gdk.EVENT_STOP

        if keyval in (Gdk.KEY_Up, Gdk.KEY_KP_Up):
            self.hide_cursor()
            self.scroll_direction = Gtk.DirectionType.UP
            self.ignore_scroll_value_changes = False
            self.vadj.set_value(self.vadj.get_value() - self.vadj.get_step_increment())
            return Gdk.EVENT_STOP

        if keyval in (Gdk.KEY_Left, Gdk.KEY_KP_Left):
            self.hide_cursor()
            self.scroll_to_direction('left')
            return Gdk.EVENT_STOP

        if keyval in (Gdk.KEY_Right, Gdk.KEY_KP_Right):
            self.hide_cursor()
            self.scroll_to_direction('right')
            return Gdk.EVENT_STOP

        return Gdk.EVENT_PROPAGATE

    def on_page_status_changed(self, page, _param):
        if page.status == 'rendering':
            return

        if page not in self.pages:
            print('ALREADY removed page !!!', page.status, page.index)
            return

        # if page.status == 'rendered':
        self.adjust_scroll()

    def on_scroll_upper_changed(self, *args):
        pass

        # self.adjust_scroll()

    def on_scroll(self, _controller, _dx, dy):
        self.scroll_direction = Gtk.DirectionType.UP if dy < 0 else Gtk.DirectionType.DOWN
        scroll_value = self.vadj.get_value() + dy

        if self.scroll_direction == Gtk.DirectionType.UP:
            position = self.get_position(scroll_value)
        else:
            position = self.get_position(scroll_value + self.reader.size.height)
        page = self.pages[position]

        if page != self.current_page:
            if not page.loadable:
                # Cancel scroll
                value = self.get_page_offset(self.current_page)
                if self.scroll_direction == Gtk.DirectionType.DOWN:
                    _minimal, natural = self.current_page.get_preferred_size()
                    value -= self.reader.size.height - natural.height
                self.adjust_scroll(value=value, emit_signal=False)

                if page.status == 'offlimit':
                    if self.scroll_direction == Gtk.DirectionType.DOWN:
                        message = _('It was the last chapter.')
                    else:
                        message = _('There is no previous chapter.')
                    self.window.show_notification(message, 2)
                else:
                    self.window.show_notification(_('This chapter is inaccessible.'), 2)

                return

            # Disable navigation: it will be re-enabled if page is loadable
            self.interactive = False

            self.current_page = page
            self.current_page_scroll_value = scroll_value - self.get_page_offset(page)

            GLib.idle_add(self.update, page)
            GLib.idle_add(self.save_progress, page)

            GLib.idle_add(self.add_page, Gtk.PositionType.TOP if self.scroll_direction == Gtk.DirectionType.UP else Gtk.PositionType.BOTTOM)
        else:
            self.current_page_scroll_value = scroll_value - self.get_page_offset(page)

    def on_single_click(self, x, _y):
        if x >= self.reader.size.width / 3 or x <= 2 * self.reader.size.width / 3:
            # Center part of the page: toggle controls
            self.reader.toggle_controls()

    def scroll_to_direction(self, direction):
        value = self.vadj.get_value()

        if direction == 'right':
            self.scroll_direction = Gtk.DirectionType.DOWN
            value += self.reader.size.height * 2 / 3
        else:
            self.scroll_direction = Gtk.DirectionType.UP
            value -= self.reader.size.height * 2 / 3

        self.vadj.set_value(value)

    def set_orientation(self, _orientation):
        return

    def update(self, page, _index=None):
        if page not in self.pages:
            return GLib.SOURCE_REMOVE

        if not page.loadable and page.error is None:
            # Loop until page is loadable or page is on error
            return GLib.SOURCE_CONTINUE

        if page.loadable:
            self.interactive = True
            # print('interactive')

        # Update title, initialize controls and notify user if chapter changed
        if self.current_chapter_id != page.chapter.id:
            self.current_chapter_id = page.chapter.id
            self.reader.update_title(page.chapter)
            self.window.show_notification(page.chapter.title, 2)
            self.reader.controls.init(page.chapter)

        # Update page number and controls page slider
        self.reader.update_page_number(page.index + 1, len(page.chapter.pages) if page.loadable else None)
        self.reader.controls.set_scale_value(page.index + 1)

        return GLib.SOURCE_REMOVE
