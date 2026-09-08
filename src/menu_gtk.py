#!/usr/bin/env python3
# WProton - menus GTK
#
# Copyright (C) 2026  stshunz y colaboradores
#
# Este programa es software libre: puedes redistribuirlo y/o modificarlo bajo
# los terminos de la Licencia Publica General GNU (GPL), version 3 o
# posterior, publicada por la Free Software Foundation.
#
# Se distribuye SIN NINGUNA GARANTIA. Ver <https://www.gnu.org/licenses/>.
# Selector de WProton con foco garantizado en la lista (navegable con mando)
# Uso: menu_gtk.py <list|check> <titulo> <fichero_salida> <fichero_opciones>
#   list : una opción por linea; al elegir se escribe en salida
#   check: lineas "0|Texto" / "1|Texto"; Espacio (X) marca, Enter (A) acepta
import sys
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk

MODE, TITLE, OUTFILE, OPTFILE = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
with open(OPTFILE, encoding='utf-8') as f:
    LINES = [l.rstrip('\n') for l in f if l.strip()]

class Win(Gtk.Window):
    def __init__(self):
        super().__init__(title='WProton')
        self.set_default_size(660, 640)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.set_keep_above(True)
        self.set_type_hint(Gdk.WindowTypeHint.DIALOG)
        v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        v.set_margin_top(10); v.set_margin_bottom(10)
        v.set_margin_start(10); v.set_margin_end(10)
        lbl = Gtk.Label(label=TITLE); lbl.set_xalign(0); lbl.set_line_wrap(True)
        v.pack_start(lbl, False, False, 0)

        if MODE == 'check':
            self.store = Gtk.ListStore(bool, str)
            for l in LINES:
                on, _, txt = l.partition('|')
                self.store.append([on == '1', txt])
        else:
            self.store = Gtk.ListStore(str)
            for l in LINES:
                self.store.append([l])

        self.tv = Gtk.TreeView(model=self.store)
        self.tv.set_headers_visible(False)
        if MODE == 'check':
            tog = Gtk.CellRendererToggle()
            tog.connect('toggled', self.on_toggled)
            self.tv.append_column(Gtk.TreeViewColumn('', tog, active=0))
            self.tv.append_column(Gtk.TreeViewColumn('', Gtk.CellRendererText(), text=1))
        else:
            self.tv.append_column(Gtk.TreeViewColumn('', Gtk.CellRendererText(), text=0))
        self.tv.connect('row-activated', self.on_activate)
        sw = Gtk.ScrolledWindow(); sw.set_vexpand(True); sw.add(self.tv)
        v.pack_start(sw, True, True, 0)

        hint = 'A/Enter: elegir   B/Esc: volver' if MODE == 'list' \
               else 'X/Espacio: marcar   A/Enter: aceptar   B/Esc: cancelar'
        h = Gtk.Label(label=hint); h.set_xalign(0)
        h.get_style_context().add_class('dim-label')
        v.pack_start(h, False, False, 0)

        self.add(v)
        self.connect('key-press-event', self.on_key)
        self.connect('destroy', Gtk.main_quit)
        self.show_all()
        # === LA CLAVE: primera fila seleccionada y foco en la lista ===
        self.tv.set_cursor(Gtk.TreePath.new_first())
        self.tv.grab_focus()

    def cursor_row(self):
        path, _ = self.tv.get_cursor()
        return None if path is None else self.store[path]

    def on_toggled(self, cell, path):
        self.store[path][0] = not self.store[path][0]

    def on_activate(self, tv, path, col):
        if MODE == 'check':
            self.accept()
        else:
            with open(OUTFILE, 'w', encoding='utf-8') as f:
                f.write(self.store[path][0])
            Gtk.main_quit()

    def accept(self):
        with open(OUTFILE, 'w', encoding='utf-8') as f:
            f.write('|'.join(r[1] for r in self.store if r[0]))
        Gtk.main_quit()

    def on_key(self, w, ev):
        if ev.keyval == Gdk.KEY_Escape:
            Gtk.main_quit()
            return True
        if MODE == 'check':
            if ev.keyval == Gdk.KEY_space:
                row = self.cursor_row()
                if row is not None:
                    row[0] = not row[0]
                return True
            if ev.keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
                self.accept()
                return True
        return False

Win()
Gtk.main()
