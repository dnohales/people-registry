# -*- coding: utf-8 -*-
import re
import sqlite3
import os

import datetime
import gi
gi.require_version('Gtk', '3.0')  # noqa
from gi.repository import Gtk, GObject, GLib


def show_message_dialog(parent, type, text, secondary_text):
    dialog = Gtk.MessageDialog(parent, 0, type, Gtk.ButtonsType.OK, text)
    dialog.format_secondary_text(secondary_text)
    dialog.run()
    dialog.destroy()


class Person(object):
    def __init__(self):
        self.id = None
        self.name = None
        self.lastname = None
        self.birthdate = None


class PersonModel(Gtk.ListStore):
    def __init__(self):
        Gtk.ListStore.__init__(self, str, str, object)

    def get_object(self, path):
        return self[path][2]

    def append_person(self, person):
        self.append(['{} {}'.format(person.name, person.lastname),
                     person.birthdate.isoformat(),
                     person])

    def refresh(self, database, search=None):
        self.clear()
        for person in database.fetch_all(search):
            self.append_person(person)


class Database(GObject.GObject):
    __gsignals__ = {
        'change': (GObject.SIGNAL_RUN_FIRST, None, ())
    }

    def __init__(self):
        GObject.GObject.__init__(self)
        self.conn = None

    def is_opened(self):
        return self.conn is not None

    def open(self, filename):
        if self.conn:
            self.conn.close()
        self.conn = sqlite3.connect(filename, isolation_level=None)
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS person (
                id INTEGER PRIMARY KEY,
                name,
                lastname,
                birthdate
            );
            """)
        self.emit('change')

    def _get_person_values(self, person):
        return person.name, person.lastname, person.birthdate.isoformat()

    def add(self, person):
        self.conn.execute('INSERT INTO person(name, lastname, birthdate) VALUES (?, ?, ?)',
                          self._get_person_values(person))
        self.emit('change')

    def update(self, person):
        self.conn.execute('UPDATE person SET (name, lastname, birthdate) = (?, ?, ?) WHERE id = ?',
                          self._get_person_values(person) + (person.id,))
        self.emit('change')

    def delete(self, person):
        self.conn.execute('DELETE FROM person WHERE id = ?', (person.id,))
        self.emit('change')

    def _create_person_object(self, person_data):
        person = Person()
        person.id = person_data[0]
        person.name = person_data[1]
        person.lastname = person_data[2]
        person.birthdate = datetime.datetime.strptime(person_data[3], '%Y-%m-%d').date()
        return person

    def fetch_all(self, search=None):
        query = 'SELECT * FROM person'
        if search:
            search = search.replace('"', '')
            query += ' WHERE LOWER(name) LIKE "%{0}%" OR LOWER(lastname) LIKE "%{0}%"'.format(
                search.lower())
        rows = self.conn.execute(query).fetchall()
        return [self._create_person_object(row) for row in rows]


class Config(object):
    def _get_config_directory(self):
        return os.path.join(GLib.get_user_config_dir(),
                            'nohales.org', 'people-registry')

    def _get_latest_database_config_filename(self):
        return os.path.join(self._get_config_directory(),
                            'latest-database-filename')

    def get_latest_database_filename(self):
        config_filename = self._get_latest_database_config_filename()
        try:
            with open(config_filename, 'r') as f:
                return f.read()
        except IOError:
            return None

    def save_latest_database_filename(self, filename):
        config_directory = self._get_config_directory()
        if not os.path.exists(config_directory):
            os.makedirs(config_directory)

        config_filename = self._get_latest_database_config_filename()
        try:
            with open(config_filename, 'w') as f:
                f.write(filename)
        except IOError:
            pass


class PersonDialog(Gtk.Dialog):
    def __init__(self, person, **kwargs):
        self.person = person
        title = 'Añadir persona' if self.person is None else 'Editar persona'

        Gtk.Dialog.__init__(self, title=title, **kwargs)

        builder = Gtk.Builder.new_from_file('persondialog.ui')
        builder.connect_signals(self)

        headerbar = builder.get_object('headerbar')
        headerbar.props.title = self.props.title
        self.set_titlebar(headerbar)

        self.name_entry = builder.get_object('name_entry')
        self.lastname_entry = builder.get_object('lastname_entry')
        self.birthdate_entry = builder.get_object('birthdate_entry')

        if self.person is None:
            builder.get_object('delete_button').hide()
            self.person = Person()
        else:
            self.name_entry.set_text(self.person.name)
            self.lastname_entry.set_text(self.person.lastname)
            self.birthdate_entry.set_text(
                self.person.birthdate.strftime(
                '%d/%m/%Y'))

        self.get_content_area().add(builder.get_object('grid'))

    def on_cancel_clicked(self, widget):
        self.response(Gtk.ResponseType.CANCEL)

    def on_delete_clicked(self, widget):
        self.person = None
        self.response(Gtk.ResponseType.OK)

    def on_save_clicked(self, widget):
        self.save()

    def on_activate(self, widget):
        self.save()

    def save(self):
        try:
            self.person.name = self.name_entry.get_text()
            self.person.lastname = self.lastname_entry.get_text()
            self.person.birthdate = datetime.datetime.strptime(
                self.birthdate_entry.get_text(), '%d/%m/%Y').date()
            self.response(Gtk.ResponseType.OK)
        except Exception as e:
            show_message_dialog(
                self, Gtk.MessageType.ERROR,
                'Error en el formulario',
                'Ocurrió un error al procesar el formulario: {}.'.format(e))


class MainWindow(Gtk.Window):
    def __init__(self):
        Gtk.Window.__init__(self, title='Registro de personas',
                            width_request=640, height_request=480)

        builder = Gtk.Builder.new_from_file('mainwindow.ui')
        builder.connect_signals(self)

        self.headerbar = builder.get_object('headerbar')
        self.headerbar.props.title = self.props.title
        self.set_titlebar(self.headerbar)

        self.treeview = builder.get_object('treeview')
        self.treeview.set_model(PersonModel())

        self.add(builder.get_object('box'))

        self.database = Database()
        self.database.connect('change', self.on_refresh_treeview)

        self.config = Config()

        self.connect('key-press-event', self.on_key_press_event)
        self.searchbar = builder.get_object('searchbar')
        search_toggle = builder.get_object('search_toggle')
        self.searchbar.bind_property('search-mode-enabled',
                                     search_toggle, 'active',
                                     GObject.BindingFlags.BIDIRECTIONAL)

    def start(self):
        self.show_all()
        self.perform_startup_database_opening()

    def refresh_treeview(self, search=None):
        self.treeview.get_model().refresh(self.database, search)

    def on_refresh_treeview(self, database):
        self.refresh_treeview()
        self.searchbar.props.search_mode_enabled = False

    def open_person_dialog(self, person):
        dialog = PersonDialog(person, parent=self)
        response = dialog.run()
        dialog.destroy()

        return response, dialog.person

    def on_row_activated(self, widget, path, column):
        person = self.treeview.get_model().get_object(path)
        response, updated_person = self.open_person_dialog(person)

        if response == Gtk.ResponseType.OK:
            if updated_person is None:
                self.database.delete(person)
            else:
                self.database.update(person)

    def on_add_person_clicked(self, widget):
        response, person = self.open_person_dialog(None)

        if response == Gtk.ResponseType.OK:
            self.database.add(person)

    def on_key_press_event(self, window, event):
        return self.searchbar.handle_event(event)

    def on_search_changed(self, entry):
        self.refresh_treeview(entry.get_text())

    def open_database(self, filename, create, update_latest=True):
        try:
            if create:
                f = open(filename, 'w')
                f.close()
            self.database.open(filename)
        except Exception as e:
            show_message_dialog(
                self, Gtk.MessageType.ERROR,
                'Error al abrir base de datos',
                'Ocurrió un error al abrir la base de datos: {}.'.format(e))
            return False

        if update_latest:
            self.config.save_latest_database_filename(filename)

        self.headerbar.props.subtitle = filename.replace(GLib.get_home_dir(), '~')

        return True

    def on_new_database_activated(self, *args):
        dialog = Gtk.FileChooserDialog(
            'Elija donde guardar la base de datos', self,
            Gtk.FileChooserAction.SAVE,
            (Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
             Gtk.STOCK_OPEN, Gtk.ResponseType.OK))
        dialog.props.do_overwrite_confirmation = True

        response = dialog.run()
        filename = dialog.get_filename()
        dialog.destroy()

        if response == Gtk.ResponseType.OK:
            return self.open_database(filename, True)

        return False

    def on_open_database_activated(self, *args):
        dialog = Gtk.FileChooserDialog(
            'Escoja el archivo de base de datos', self,
            Gtk.FileChooserAction.OPEN,
            (Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
             Gtk.STOCK_OPEN, Gtk.ResponseType.OK))

        response = dialog.run()
        filename = dialog.get_filename()
        dialog.destroy()

        if response == Gtk.ResponseType.OK:
            return self.open_database(filename, False)

        return False

    def perform_startup_database_opening(self):
        latest_database_filename = self.config.get_latest_database_filename()
        if latest_database_filename and os.path.exists(latest_database_filename):
            self.open_database(latest_database_filename, False, False)
        else:
            dialog = Gtk.MessageDialog(
                self, 0, Gtk.MessageType.QUESTION,
                Gtk.ButtonsType.NONE, 'Comencemos')
            dialog.format_secondary_text(
                'Por favor, elija una de las siguientes opciones')
            dialog.add_button('Crear nueva base de datos', 0)
            dialog.add_button('Abrir base de datos existente', 1)
            dialog.add_button('Salir', 2)

            response = dialog.run()
            dialog.destroy()

            if response == 0:
                success = self.on_new_database_activated()
            elif response == 1:
                success = self.on_open_database_activated()
            else:
                self.close()
                return

            if not success:
                self.perform_startup_database_opening()


win = MainWindow()
win.connect('delete-event', Gtk.main_quit)
win.start()
Gtk.main()
