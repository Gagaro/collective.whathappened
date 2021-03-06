import datetime
import json
import logging
import time
import os
import sqlite3

from zope import event
from zope import interface
from Products.CMFCore.utils import getToolByName

from .notification import Notification
from .subscription import Subscription
from .event import SubscribedEvent
from .event import BlacklistedEvent

logger = logging.getLogger('collective.whathappened')


def dict_factory(cursor, row):
    d = {}
    for idx, col in enumerate(cursor.description):
        d[col[0]] = row[idx]
    return d


class IStorageBackend(interface.Interface):
    """A storage backend is a named utility able to store and retrieve
    notifications and subscriptions for a specific user
    (the authenticated one by default)."""

    def initialize():
        """Initialize the storage backend to start a storage session."""

    def terminate():
        """Finish a storage session."""

    def validateBackend():
        """Check if the backend is ok."""

    def setUser(user):
        """change the user the storage is working on."""

    def getUser():
        """get the user the storage is working on."""

    def storeNotification(notification):
        """Store a notification."""

    def removeNotification(notification):
        """Remove a notification"""

    def getHotNotifications():
        """Get all "hot" notifications. Hot notifications are notifications the
        user may be the more interested in."""

    def getAllNotifications():
        """Get all notifications."""

    def getUnseenNotifications():
        """Get all unseen notifications."""

    def setSeen(path):
        """Set seen to true for the given path,
        or all notifications if no path is given."""

    def getUnseenCount():
        """Get number of unseen notification."""

    def getLastNotificationTime():
        """Get the date and time of the last notification.

        Return: a datetime object"""

    def clean():
        """Remove old notifications. It is up to the implementation to decide
        what "old notification" are (e.g.: notifications older than 7 days)."""

    def saveSubscription(subscription):
        """Store a subscription or update it."""

    def getSubscription(where):
        """Get the subscription corresponding to 'where'."""

    def getSubscriptions():
        """Get all subscriptions of the user."""


class SqliteStorageBackend(object):
    interface.implements(IStorageBackend)

    def __init__(self, context, request):
        self.context = context
        self.request = request
        self.mtool = getToolByName(self.context, 'portal_membership')
        self.user = self.mtool.getAuthenticatedMember().getId()
        self.directory = os.environ.get(
            'collective_whathappened_sqlite_directory', None)
        self.db_path = None
        self.db = None

    def initialize(self):
        if self.db is not None or self.user is None:
            return
        self.db_path = os.path.join(self.directory, '%s.sqlite' % self.user)
        self.db = sqlite3.connect(self.db_path)
        self.db.row_factory = dict_factory
        self.db.execute(
            '''
            CREATE TABLE IF NOT EXISTS notifications(
            `what`      TEXT,
            `when`      INTEGER,
            `where`     TEXT,
            `seen`      INTEGER,
            `gatherer`  TEXT,
            `info`      TEXT,
            PRIMARY KEY(`what`, `when`, `where`))
            '''
        )
        self.db.execute(
            '''
            CREATE TABLE IF NOT EXISTS notifications_who(
            `what`      TEXT,
            `when`      INTEGER,
            `where`     TEXT,
            `who`       INTEGER,
            PRIMARY KEY(`what`, `when`, `where`, `who`),
            FOREIGN KEY(`what`, `when`, `where`)
              REFERENCES notifications(`what`, `when`, `where`)
              ON DELETE CASCADE)
            '''
        )
        self.db.execute(
            '''
            CREATE TABLE IF NOT EXISTS subscriptions(
            `where`     TEXT PRIMARY KEY,
            `wants`     INTEGER)
            '''
        )

    def terminate(self):
        if self.db is None:
            return
        self.db.commit()
        self.db.close()
        self.db = None

    def validateBackend(self):
        try:
            self.initialize()
            self.getHotNotifications()
            self.terminate()
            return True
        except Exception as e:
            logger.error(e)
            return False

    def _notificationExist(self, notification):
        count = self.db.execute("""
            SELECT COUNT(*)
            FROM notifications
            WHERE `what` = ? AND `where` = ? AND `info` = ? AND seen = 0
        """, [notification.what,
              notification.where,
              json.dumps(notification.info)]).fetchone()['COUNT(*)']
        if count > 0:
            return True
        return False

    def _updateNotification(self, notification):
        self.db.execute("""
            SELECT `when`
            FROM notifications
            WHERE `what` = ? AND `where` = ? and seen = 0
        """, [notification.what, notification.where]).fetchone()['when']
        for who in notification.who:
            try:
                self.db.execute(
                    """
                    INSERT INTO notifications_who (`what`, `when`,
                                                   `where`, `who`)
                    VALUES (?, ?, ?, ?)
                    """,
                    [
                        notification.what,
                        notification.getWhenTimestamp(),
                        notification.where,
                        who,
                    ]
                )
            except sqlite3.IntegrityError:
                pass

    def _createNotification(self, notification):
        self.db.execute(
            """
                INSERT INTO notifications (`what`, `when`, `where`,
                                           `seen`, `gatherer`, `info`)
                VALUES (?, ?, ?, ?, ?, ?)
            """,
            [notification.what,
             notification.getWhenTimestamp(),
             notification.where,
             notification.seen,
             notification.gatherer,
             json.dumps(notification.info)]
        )
        for who in notification.who:
            self.db.execute(
                """
                    INSERT INTO notifications_who (`what`, `when`,
                                                   `where`, `who`)
                    VALUES (?, ?, ?, ?)
                """,
                [notification.what,
                 notification.getWhenTimestamp(),
                 notification.where,
                 who]
            )

    def storeNotification(self, notification):
        if self.db is None:
            return
        try:
            if self._notificationExist(notification):
                self._updateNotification(notification)
            else:
                self._createNotification(notification)
        except sqlite3.IntegrityError:
            pass

    def removeNotification(self, notification):
        if self.db is None:
            return
        try:
            self.db.execute(
                """DELETE FROM notifications
                   WHERE `what` = ? AND `when` = ? AND `where` = ?""",
                [notification.what,
                 notification.getWhenTimestamp(),
                 notification.where]
            )
        except sqlite3.IntegrityError:
            pass

    def _createNotificationFromResult(self, result):
        if result['who'] is None:
            who = []
        else:
            who = result['who'].split(', ')
        if result['info'] is None:
            info = None
        else:
            info = json.loads(result['info'])
        notification = Notification(
            result['what'],
            result['where'],
            datetime.datetime.fromtimestamp(result['when']),
            who,
            self.user,
            result['gatherer'],
            result['seen'],
            info,
        )
        return notification

    def getHotNotifications(self):
        if self.db is None:
            return []
        results = self.db.execute(
            """
            SELECT
                n.`what`,
                n.`when`,
                n.`where`,
                GROUP_CONCAT(nw.`who`, ', ') as `who`,
                n.`gatherer`,
                n.`seen`,
                n.`info`
            FROM notifications n
            LEFT JOIN notifications_who nw
                ON n.`what` = nw.`what`
                AND n.`when` = nw.`when`
                AND n.`where` = nw.`where`
            GROUP BY n.`what`, n.`when`, n.`where`
            ORDER BY n.`seen` ASC, n.`when` DESC
            LIMIT 5
            """
        ).fetchall()
        notifications = []
        for result in results:
            notifications.append(self._createNotificationFromResult(result))
        return notifications

    def getAllNotifications(self):
        if self.db is None:
            return []
        results = self.db.execute(
            """
            SELECT
                n.`what`,
                n.`when`,
                n.`where`,
                GROUP_CONCAT(nw.`who`, ', ') as `who`,
                n.`gatherer`,
                n.`seen`,
                n.`info`
            FROM notifications n
            INNER JOIN notifications_who nw
                ON n.`what` = nw.`what`
                AND n.`when` = nw.`when`
                AND n.`where` = nw.`where`
            GROUP BY n.`what`, n.`when`, n.`where`
            ORDER BY n.`when` DESC
            """
        ).fetchall()
        notifications = []
        for result in results:
            notifications.append(self._createNotificationFromResult(result))
        return notifications

    def getUnseenNotifications(self):
        if self.db is None:
            return []
        results = self.db.execute(
            """
            SELECT
                n.`what`,
                n.`when`,
                n.`where`,
                GROUP_CONCAT(nw.`who`, ', ') as `who`,
                n.`gatherer`,
                n.`seen`,
                n.`info`
            FROM notifications n
            INNER JOIN notifications_who nw
                ON n.`what` = nw.`what`
                AND n.`when` = nw.`when`
                AND n.`where` = nw.`where`
            WHERE n.`seen` = 0
            GROUP BY n.`what`, n.`when`, n.`where`
            ORDER BY n.`when` DESC
            """
        ).fetchall()
        notifications = []
        for result in results:
            notifications.append(self._createNotificationFromResult(result))
        return notifications

    def setSeen(self, path=None):
        if path is None:
            self.db.execute("UPDATE notifications SET seen = 1")
        else:
            self.db.execute(
                "UPDATE notifications SET seen = 1 WHERE `where` = ?",
                [path]
            )

    def clean(self):
        lastWeek = datetime.datetime.now() - datetime.timedelta(7)
        timestamp = time.mktime(lastWeek.timetuple())
        self.db.execute("REMOVE FROM notifications WHERE `when` < ?",
                        [timestamp])

    def getUnseenCount(self):
        if self.db is None:
            return 0
        query = self.db.execute("SELECT COUNT(*) FROM notifications "
                                "WHERE `seen` = 0")
        unseen = query.fetchone()['COUNT(*)']
        return unseen

    def getLastNotificationTime(self):
        try:
            req = ("SELECT `when` FROM notifications "
                   "ORDER BY `when` DESC LIMIT 1")
            result = self.db.execute(req).fetchone()
            lastTime = datetime.datetime.fromtimestamp(result['when'])
        except:
            lastTime = datetime.datetime.now() - datetime.timedelta(7)
        return lastTime

    def saveSubscription(self, subscription):
        try:
            if subscription.wants is None:
                self.db.execute("DELETE FROM subscriptions WHERE `where` = ?",
                                [subscription.where])
            else:
                self.db.execute("INSERT INTO subscriptions "
                                "(`where`, `wants`) VALUES (?, ?)",
                                [subscription.where, subscription.wants])
        except sqlite3.IntegrityError:
            self.db.execute("UPDATE subscriptions SET `wants` = ? "
                            "WHERE `where` = ?",
                            [subscription.wants, subscription.where])
        if subscription is None or not subscription.wants:
            self.db.execute("DELETE FROM notifications WHERE `where` LIKE ?",
                            ['%s%%' % subscription.where])
        if subscription is None:
            pass
        elif subscription.wants:
            event.notify(SubscribedEvent(subscription.where))
        else:
            event.notify(BlacklistedEvent(subscription.where))

    def _createSubscriptionFromResult(self, result):
        wants = result['wants'] == 1
        subscription = Subscription(result['where'], wants)
        return subscription

    def getSubscription(self, where):
        results = self.db.execute("SELECT * FROM subscriptions "
                                  "WHERE `where` = ?",
                                  [where]).fetchall()
        if len(results) == 0:
            return None
        return self._createSubscriptionFromResult(results[0])

    def getSubscriptions(self):
        results = self.db.execute("SELECT * FROM subscriptions").fetchall()
        subscriptions = []
        for result in results:
            subscriptions.append(self._createSubscriptionFromResult(result))
        return subscriptions

    def setUser(self, user):
        if self.db is not None:
            return
        self.user = user

    def getUser(self):
        return self.user


class NullBackend(object):
    """ Null backend used in case the other backend is not valid."""
    interface.implements(IStorageBackend)

    def initialize(self):
        pass

    def terminate(self):
        pass

    def validateBackend(self):
        return True

    def setUser(self, user):
        pass

    def getUser(self):
        return ''

    def storeNotification(self, notification):
        pass

    def removeNotification(self, notification):
        pass

    def getHotNotifications(self):
        return []

    def getAllNotifications(self):
        return []

    def getUnseenNotifications(self):
        return []

    def setSeen(self, path=None):
        pass

    def getUnseenCount(self):
        return 0

    def getLastNotificationTime(self):
        return datetime.datetime.now()

    def clean(self):
        pass

    def saveSubscription(self, subscription):
        pass

    def getSubscription(self, where):
        return None

    def getSubscriptions(self):
        return []
