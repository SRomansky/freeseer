#!/usr/bin/python
# -*- coding: utf-8 -*-

# freeseer - vga/presentation capture software
#
#  Copyright (C) 2011, 2013  Free and Open Source Software Learning Centre
#  http://fosslc.org
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program.  If not, see <http://www.gnu.org/licenses/>.

# For support, questions, suggestions or any other inquiries, visit:
# http://wiki.github.com/Freeseer/freeseer/

import csv
import logging

from PyQt4 import QtSql
from PyQt4.QtCore import QDate
from PyQt4.QtCore import QTime
from PyQt4.QtCore import QStringList

from freeseer import SCHEMA_VERSION
from freeseer.framework.presentation import Presentation
from freeseer.framework.failure import Failure, Report

log = logging.getLogger(__name__)


# Database Schema Versions
PRESENTATIONS_SCHEMA_300 = '''CREATE TABLE IF NOT EXISTS presentations
                                       (Id INTEGER PRIMARY KEY,
                                        Title varchar(255),
                                        Speaker varchar(100),
                                        Description text,
                                        Level varchar(25),
                                        Event varchar(100),
                                        Room varchar(25),
                                        Time timestamp,
                                        UNIQUE (Speaker, Title) ON CONFLICT IGNORE)'''

# FIXME: Document what is Date, StartTime, EndTime below.
# From CSV/RSS they look like yyyy-mm-ddThh:mm:ss
PRESENTATIONS_SCHEMA_310 = '''CREATE TABLE IF NOT EXISTS presentations
                                       (Id INTEGER PRIMARY KEY,
                                        Title varchar(255),
                                        Speaker varchar(100),
                                        Description text,
                                        Category varchar(25),
                                        Event varchar(100),
                                        Room varchar(25),
                                        Date timestamp,
                                        StartTime timestamp,
                                        EndTime timestamp,
                                        UNIQUE (Speaker, Title) ON CONFLICT IGNORE)'''

REPORTS_SCHEMA_300 = '''CREATE TABLE IF NOT EXISTS failures
                                        (Id INTERGER PRIMARY KEY,
                                        Comments TEXT,
                                        Indicator TEXT,
                                        Release INTEGER,
                                        UNIQUE (ID) ON CONFLICT REPLACE)'''


class QtDBConnector(object):
    def __init__(self, db_filepath, plugman):
        """
        Initialize the QtDBConnector
        """
        self.talkdb_file = db_filepath
        self.plugman = plugman

        self.presentationsModel = None
        self.failuresModel = None
        self.__open_table()

    def __open_table(self):
        """Opens a connection to the database. Uses by the init function."""
        self.talkdb = QtSql.QSqlDatabase.addDatabase("QSQLITE")
        self.talkdb.setDatabaseName(self.talkdb_file)

        if self.talkdb.open():

            # check if presentations table exists and if not create it.
            if not self.talkdb.tables().contains("presentations"):
                self._create_presentations_table()

                # If presentations table did not exist, it is safe to say that the reports table needs to be reset
                # or initialized.
                self.drop_report_db()
                self.__create_failures_table()

                # Set the database version (so the updater does not update)
                QtSql.QSqlQuery('PRAGMA user_version = {}'.format(SCHEMA_VERSION))

            # verify that correct version of database exists
            self._update_version()
        else:
            log.error("Unable to create talkdb file.")

    def __close_table(self):
        """Closes the connection the the database."""
        self.talkdb.close()

    def _get_db_version_int(self):
        """Gets the database's current version. Default is 0 if unset (for 2x and older)"""
        query = QtSql.QSqlQuery('PRAGMA user_version')
        query.first()
        return query.value(0).toInt()[0]

    def _update_version(self):
        """Upgrade database to the latest SCHEMA_VERSION"""

        db_version = self._get_db_version_int()
        if db_version == SCHEMA_VERSION:
            return
        #
        # Define functions for upgrading between schema versions
        #

        def update_2xto30():
            """Incremental update of database from Freeseer 2.x and older to 3.0

            SCHEMA_VERSION is 300
            """
            if db_version > 300:
                log.debug('Database newer than schema version 300.')
                return  # No update needed

            log.debug('Updating to schema 300.')
            QtSql.QSqlQuery('ALTER TABLE presentations RENAME TO presentations_old')  # temporary table
            self._create_presentations_table(PRESENTATIONS_SCHEMA_300)
            QtSql.QSqlQuery("""INSERT INTO presentations
                            SELECT Id, Title, Speaker, Description, Level, Event, Room, Time FROM presentations_old""")
            QtSql.QSqlQuery('DROP TABLE presentations_old')

        def update_30to31():
            """Performs incremental update of database from 3.0 and older to 3.1."""
            QtSql.QSqlQuery('ALTER TABLE presentations RENAME TO presentations_old')
            self._create_presentations_table(PRESENTATIONS_SCHEMA_310)
            QtSql.QSqlQuery("""INSERT INTO presentations
                            SELECT Id, Title, Speaker, Description, Level, Event, Room, Time, Time, Time
                            FROM presentations_old""")
            QtSql.QSqlQuery('DROP TABLE presentations_old')

        #
        # Perform the upgrade
        #
        updaters = [update_2xto30, update_30to31]
        for updater in updaters:
            updater()

        QtSql.QSqlQuery('PRAGMA user_version = {}'.format(SCHEMA_VERSION))
        log.info('Upgraded presentations database from version %d to %d', db_version, SCHEMA_VERSION)

    def _create_presentations_table(self, schema=PRESENTATIONS_SCHEMA_310):
        """Creates the presentations table in the database. Should be used to initialize a new table."""
        log.info("table created")
        QtSql.QSqlQuery(schema)

    def get_talks(self):
        """Gets all the talks from the database including all columns"""
        return QtSql.QSqlQuery('SELECT * FROM presentations')

    def get_talk_ids(self):
        """Gets all the talk events from the database"""
        return QtSql.QSqlQuery('SELECT Id FROM presentations')

    def get_talks_by_event(self, event):
        """Gets the talks signed in a specific event from the database"""
        return QtSql.QSqlQuery('SELECT * FROM presentations WHERE Event="{}"'.format(event))

    def get_talks_by_room(self, room):
        """Gets the talks hosted in a specific room from the database"""
        return QtSql.QSqlQuery('SELECT * FROM presentations WHERE Room="{}"'.format(room))

    def get_talks_by_room_and_time(self, room):
        """Returns the talks hosted in a specified room, starting from the current date and time"""
        current_date = QDate.currentDate().toString(1)  # yyyy-mm-dd
        current_time = QTime.currentTime().toString()  # hh:mm:ss
        return QtSql.QSqlQuery('''SELECT * FROM presentations
                                  WHERE Room='{}' AND Date='{}'
                                  AND StartTime >= '{}' ORDER BY StartTime ASC'''.format(room, current_date, current_time))

    def get_presentation(self, talk_id):
        """Returns a Presentation object associated to a talk_id"""
        result = QtSql.QSqlQuery('SELECT * FROM presentations WHERE Id="{}"'.format(talk_id))
        if result.next():
            return Presentation(title=unicode(result.value(1).toString()),
                             speaker=unicode(result.value(2).toString()),
                             description=unicode(result.value(3).toString()),
                             category=unicode(result.value(4).toString()),
                             event=unicode(result.value(5).toString()),
                             room=unicode(result.value(6).toString()),
                             date=unicode(result.value(7).toString()),
                             startTime=unicode(result.value(8).toString()),
                             endTime=unicode(result.value(9).toString()))
        else:
            return None

    def get_presentation_id(self, presentation):
        # FIXME: This should use more than just the title and speaker to find an Id.
        """Returns a Presentation talk_id associated to a Presentation object"""
        result = QtSql.QSqlQuery('SELECT Id FROM presentations WHERE Title="{0}" and Speaker="{1}"'.format(presentation.title, presentation.speaker))
        if result.next():
            return unicode(result.value(0).toString())
        else:
            return None

    def get_string_list(self, column):
        """Returns a column as a QStringList"""
        tempList = QStringList()
        result = QtSql.QSqlQuery('SELECT DISTINCT {} FROM presentations'.format(column))
        while result.next():
            tempList.append(result.value(0).toString())
        return tempList

    def _helper_presentation_exists(self, presentation):
        """This is used in testing. Checks if there's a presentation with the same Speaker and Title already stored."""
        # FIXME/TODO, For some reason when the python value '' is passed into the QSqlQuery, it is not seen as ''. In
        # SQL '' is NULL. So the query looks for a row with a magical value in it that can never actually exist...
        if presentation.room == '':
            presentation.room = None
        result = QtSql.QSqlQuery('''
            SELECT *
            FROM presentations
            WHERE Title="{0}" AND Speaker="{1}" AND Description="{2}" AND Category="{3}" AND
                  Event="{4}" AND (Room="{5}" OR Room is NULL) AND (Date="{6}" OR Date is NULL) AND
                  (StartTime="{7}" or StartTime is Null) AND EndTime="{8}"
        '''.format(
            presentation.title, presentation.speaker, presentation.description, presentation.category,
            presentation.event, presentation.room, presentation.date, presentation.startTime,
            presentation.endTime
        ))
        if result.next():
            return True
        else:
            return False

    #
    # Presentation Create, Update, Delete
    #
    def insert_presentation(self, presentation):
        """Inserts a passed Presentation into the database."""
        # Duplicate time to date field for older RSS / CSV formats
        # If date is empty, and time has a full DateTime, split the DateTime to
        # both Date and Time

        if not presentation.date and presentation.startTime and len(presentation.startTime) == 16:
            presentation.date, presentation.startTime = presentation.startTime[:-6], presentation.startTime[11:]

        query = QtSql.QSqlQuery()
        query.prepare('''
            INSERT INTO presentations(Title, Speaker, Description, Category, Event, Room, Date, StartTime, EndTime)
            VALUES (:title, :speaker, :description, :category, :event, :room, :date, :startTime, :endTime)
        ''')
        query.bindValue(':title', presentation.title)
        query.bindValue(':speaker', presentation.speaker)
        query.bindValue(':description', presentation.description)
        query.bindValue(':category', presentation.category)
        query.bindValue(':event', presentation.event)
        query.bindValue(':room', presentation.room)
        query.bindValue(':date', presentation.date)
        query.bindValue(':startTime', presentation.startTime)
        query.bindValue(':endTime', presentation.endTime)
        query.exec_()
        log.info("Talk added: %s - %s, Time: %s - %s", presentation.speaker, presentation.title, presentation.startTime,
                 presentation.endTime)

    def update_presentation(self, talk_id, presentation):
        """Updates an existing Presentation in the database."""
        query = QtSql.QSqlQuery()
        query.prepare('''
            UPDATE presentations
            SET Title=:title, Speaker=:speaker, Description=:description, Category=:category,
                Event=:event, Room=:room, Date=:date, StartTime=:startTime, EndTime=:endTime
            WHERE Id=:talk_id
        ''')

        query.bindValue(':talk_id', talk_id)
        query.bindValue(':title', presentation.title)
        query.bindValue(':speaker', presentation.speaker)
        query.bindValue(':description', presentation.description)
        query.bindValue(':category', presentation.category)
        query.bindValue(':event', presentation.event)
        query.bindValue(':room', presentation.room)
        query.bindValue(':date', presentation.date)
        query.bindValue(':startTime', presentation.startTime)
        query.bindValue(':endTime', presentation.endTime)
        query.exec_()
        log.info("Talk %s updated: %s - %s", talk_id, presentation.speaker, presentation.title)

    def delete_presentation(self, talk_id):
        """Removes a Presentation from the database"""
        QtSql.QSqlQuery('DELETE FROM presentations WHERE Id="{}"'.format(talk_id))
        log.info("Talk %s deleted.", talk_id)

    def clear_database(self):
        """Clears the presentations table"""
        QtSql.QSqlQuery('DELETE FROM presentations')
        log.info("Database cleared.")

    #
    # Data Model Retrieval
    #
    def get_presentations_model(self):
        """Gets the Presentation Table Model. Useful for Qt GUI based Frontends to load the Model in Table Views"""
        if self.presentationsModel is None:
            self.presentationsModel = QtSql.QSqlTableModel()
            self.presentationsModel.setTable("presentations")
            self.presentationsModel.setEditStrategy(QtSql.QSqlTableModel.OnFieldChange)
            self.presentationsModel.select()
        return self.presentationsModel

    def get_events_model(self):
        """Gets the Events Model. Useful for Qt GUI based Frontends to load the Model into Views"""
        self.eventsModel = QtSql.QSqlQueryModel()
        self.eventsModel.setQuery("SELECT DISTINCT Event FROM presentations ORDER BY Event ASC")
        return self.eventsModel

    def get_dates_from_event_room_model(self, event, room):
        """Gets the Dates Model. Useful for Qt GUI based Frontends to load the Model into Views."""
        self.datesModel = QtSql.QSqlQueryModel()
        self.datesModel.setQuery(
            "SELECT DISTINCT date FROM presentations \
            WHERE Event='{}' and Room='{}' ORDER BY Date ASC".format(event, room))
        return self.datesModel

    def get_rooms_model(self, event):
        """Gets the Rooms Model. Useful for Qt GUI based Frontends to load the Model into Views"""
        self.roomsModel = QtSql.QSqlQueryModel()
        self.roomsModel.setQuery("SELECT DISTINCT Room FROM presentations WHERE Event='{}' ORDER BY Room ASC".format(event))
        return self.roomsModel

    def get_talks_model(self, event, room, date=None):
        """Gets the Talks Model. A talk is defined as "<presenter> - <talk_title>"
        Useful for Qt GUI based Frontends to load the Model into Views"""
        self.talksModel = QtSql.QSqlQueryModel()
        if date == "":
            self.talksModel.setQuery(
                "SELECT (Speaker || ' - ' || Title), Id FROM presentations \
                WHERE Event='{}' and Room='{}' ORDER BY Date ASC".format(event, room))
        else:
            self.talksModel.setQuery(
                "SELECT (Speaker || ' - ' || Title), Id FROM presentations \
                WHERE Event='{}' and Room='{}' and date(Date) LIKE '{}' ORDER BY Date ASC".format(event, room, date))
        return self.talksModel

    def get_talk_between_dates(self, event, room, startDate, endDate):
        """Returns the talkID of the first talk found between a startDate, and endDate for a specified event/room.
        Else return None"""
        # FIXME: This function only returns one of the Id's on a given date. What if there are two presentations on the same day?
        query = QtSql.QSqlQuery("""
            SELECT Id, Date FROM presentations
            WHERE Event='{0}' AND Room='{1}'
            AND Date BETWEEN '{2}'
            AND '{3}' ORDER BY Date ASC
        """.format(event, room, startDate, endDate))

        query.next()
        if query.isValid():
            return query.value(0)
        else:
            return None

    #
    # Import / Export Functions
    #
    # Needs to be updated for category field, separate date and time fields
    def add_talks_from_rss(self, feed_url):
        """Adds talks from an rss feed."""
        plugin = self.plugman.get_plugin_by_name("Rss FeedParser", "Importer")
        feedparser = plugin.plugin_object
        presentations = feedparser.get_presentations(feed_url)

        if presentations:
            for presentation in presentations:
                talk = Presentation(presentation["Title"],
                                    presentation["Speaker"],
                                    presentation["Abstract"],  # Description
                                    presentation["Level"],
                                    presentation["Event"],
                                    presentation["Room"],
                                    presentation["Time"],
                                    presentation["Time"])
                self.insert_presentation(talk)

        else:
            log.info("RSS: No data found.")

    def add_talks_from_csv(self, fname):
        """Adds talks from a csv file.

        Title and speaker must be present.
        """
        plugin = self.plugman.get_plugin_by_name("CSV Importer", "Importer")
        importer = plugin.plugin_object
        presentations = importer.get_presentations(fname)

        if presentations:
            for presentation in presentations:
                talk = Presentation(presentation["Title"],
                                    presentation["Speaker"],
                                    presentation["Abstract"],  # Description
                                    presentation["Level"],
                                    presentation["Event"],
                                    presentation["Room"],
                                    presentation["Time"],
                                    presentation["Time"])
                self.insert_presentation(talk)

        else:
            log.info("CSV: No data found.")

    def export_talks_to_csv(self, fname):
        fieldNames = ('Title',
                      'Speaker',
                      'Abstract',
                      'Category',
                      'Event',
                      'Room',
                      'Date',
                      'StartTime',
                      'EndTime')

        with open(fname, 'w') as fd:
            writer = csv.DictWriter(fd, fieldnames=fieldNames)
            headers = dict((n, n) for n in fieldNames)
            writer.writerow(headers)

            result = self.get_talks()
            while result.next():
                log.debug(unicode(result.value(1).toString()))
                writer.writerow({'Title': unicode(result.value(1).toString()),
                                 'Speaker': unicode(result.value(2).toString()),
                                 'Abstract': unicode(result.value(3).toString()),
                                 'Category': unicode(result.value(4).toString()),
                                 'Event': unicode(result.value(5).toString()),
                                 'Room': unicode(result.value(6).toString()),
                                 'Date': unicode(result.value(7).toString()),
                                 'StartTime': unicode(result.value(8).toString()),
                                 'EndTime': unicode(result.value(9).toString())})

    def export_reports_to_csv(self, fname):
        fieldNames = ('Title',
                      'Speaker',
                      'Abstract',
                      'Category',
                      'Event',
                      'Room',
                      'Date',
                      'StartTime',
                      'EndTime',
                      'Problem',
                      'Error')
        with open(fname, 'w') as fd:
            writer = csv.DictWriter(fd, fieldnames=fieldNames)
            headers = dict((n, n) for n in fieldNames)
            writer.writerow(headers)

            result = self.get_reports()
            for report in result:
                writer.writerow({'Title': report.presentation.title,
                                 'Speaker': report.presentation.speaker,
                                 'Abstract': report.presentation.description,
                                 'Category': report.presentation.category,
                                 'Event': report.presentation.event,
                                 'Room': report.presentation.room,
                                 'Date': report.presentation.date,
                                 'StartTime': report.presentation.startTime,
                                 'EndTime': report.presentation.endTime,
                                 'Problem': report.failure.indicator,
                                 'Error': report.failure.comment})

    #
    # Reporting Feature
    #
    def __create_failures_table(self, schema=REPORTS_SCHEMA_300):
        """Creates the failures table in the database. Should be used to initialize a new table"""
        QtSql.QSqlQuery(schema)

    def clear_report_db(self):
        """Deletes reports from the failures table"""
        QtSql.QSqlQuery('DELETE FROM failures')
        log.info('failures table cleared')

    def drop_report_db(self):
        """Drops the failures (reports) table from the database"""
        QtSql.QSqlQuery('DROP TABLE IF EXISTS failures')
        log.info('failures table dropped')

    def get_report(self, talkid):
        """Returns a failure from a given talkid. Returned value is a Failure object"""
        result = QtSql.QSqlQuery('SELECT * FROM failures WHERE Id = "{}"'.format(talkid))
        if result.next():
            failure = Failure(unicode(result.value(0).toString()),  # id
                              unicode(result.value(1).toString()),  # comment
                              unicode(result.value(2).toString()),  # indicator
                              result.value(3).toBool())             # release
        else:
            failure = None
        return failure

    def get_reports(self):
        """Returns a list of failures in Report format"""
        result = QtSql.QSqlQuery('SELECT * FROM failures')
        list = []
        while result.next():
            failure = Failure(unicode(result.value(0).toString()),    # id
                              unicode(result.value(1).toString()),    # comment
                              unicode(result.value(2).toString()),    # indicator
                              bool(result.value(3)))                  # release
            p = self.get_presentation(failure.talkId)
            r = Report(p, failure)
            list.append(r)
        return list

    def insert_failure(self, failure):
        """Inserts a failure into the database"""
        QtSql.QSqlQuery(
            u'INSERT INTO failures VALUES ({}, "{}", "{}", {})'.format(failure.talkId, failure.comment,
                                                                       failure.indicator, int(failure.release)))
        log.info('Failure added: %s - %s', failure.talkId, failure.comment)

    def update_failure(self, talk_id, failure):
        """Updates an existing Failure in the database"""
        QtSql.QSqlQuery('UPDATE failures SET Comments="{}", Indicator="{}", Release="{}" WHERE Id={}'.format
                        (failure.comment, failure.indicator, failure.release, int(failure.talkId)))
        log.info("Failure updated: %s %s", failure.talkId, failure.comment)

    def delete_failure(self, talk_id):
        """Removes a Presentation from the database"""
        QtSql.QSqlQuery('DELETE FROM failures WHERE Id="{}"'.format(talk_id))
        log.info("Failure %s deleted.", talk_id)

    def get_failures_model(self):
        """Gets the Failure reports table Model. Useful for QT GUI based Frontends to load the Model in Table Views"""
        if self.failuresModel is None:
            self.failuresModel = QtSql.QSqlTableModel()
            self.failuresModel.setTable("failures")
            self.failuresModel.setEditStrategy(QtSql.QSqlTableModel.OnFieldChange)
            self.failuresModel.select()

        return self.failuresModel
