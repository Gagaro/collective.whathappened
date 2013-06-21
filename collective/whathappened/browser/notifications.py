from zope.component import getMultiAdapter
from zope.i18n import translate

from Products.Five.browser import BrowserView

from plone.app.layout.viewlets import common

from collective.whathappened.gatherer_manager import GathererManager
from collective.whathappened.storage_manager import StorageManager
from collective.whathappened.i18n import _
from collective.history.i18n import _ as _h

class AllView(BrowserView):
    def __init__(self, context, request):
        self.context = context
        self.request = request

    def __call__(self):
        self.update()
        self.setPath()
        return self.index()

    def update(self):
        self.gatherer = GathererManager(self.context, self.request)
        self.storage = StorageManager(self.context, self.request)
        self.storage.initialize()
        self.updateNotifications()
        self.notifications = self.storage.getAllNotifications()
        self.storage.terminate()
        self.notificationsCount = len(self.notifications)

    def show(self, notification):
        what = translate(_h(notification.what.decode("utf-8")), domain="collective.history", context=self.request)
        return _(u"${who} has ${what} ${where}",
                 mapping={
                     'who': notification.who,
                     'what': what,
                     'where': notification.where
                 })

    def setPath(self):
        context = self.context.aq_inner
        portal_state = getMultiAdapter((context, self.request),
                                       name=u'plone_portal_state')
        path = portal_state.navigation_root().getPhysicalPath()
        self.navigation_root = '/'.join(path)

    def updateNotifications(self):
        #@TODO: GET LAST CHECK FROM SESSION OR STORAGE
        lastCheck = self.storage.getLastNotificationTime()
        newNotifications = self.gatherer.getNewNotifications(lastCheck)
        if newNotifications is not None:
            for notification in newNotifications:
                self.storage.storeNotification(notification)


class HotViewlet(common.PersonalBarViewlet):
    def update(self):
        super(HotViewlet, self).update()
        if self.anonymous:
            return
        self.gatherer = GathererManager(self.context, self.request)
        self.storage = StorageManager(self.context, self.request)
        self.storage.initialize()
        self.updateNotifications()
        self.notifications = self.storage.getHotNotifications()
        self.unseenCount = self.storage.getUnseenCount()
        self.storage.terminate()

        self.user_name += " (%d)" % self.unseenCount
        for notification in self.notifications:
            self.user_actions.append({
                'category': 'notification',
                'available': True,
                'title': self.show(notification),
                'url': self.context.absolute_url() + notification.where,
                'visible': True,
                'allowed': True,
                'link_target': None,
                'id': 'notification'
            })

    def show(self, notification):
        what = translate(_h(notification.what.decode("utf-8")), domain="collective.history", context=self.request)
        return _(u"${who} has ${what} ${where}",
                 mapping={
                     'who': notification.who,
                     'what': what,
                     'where': notification.where
                 })

    def updateNotifications(self):
        #@TODO: GET LAST CHECK FROM SESSION OR STORAGE
        lastCheck = self.storage.getLastNotificationTime()
        newNotifications = self.gatherer.getNewNotifications(lastCheck)
        if newNotifications is not None:
            for notification in newNotifications:
                self.storage.storeNotification(notification)
