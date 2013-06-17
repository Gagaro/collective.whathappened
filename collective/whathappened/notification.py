from zope import interface
from zope import schema

class INotification(interface.Interface):
    """A notification is a set of useractions sharing the same what/where,
    and linkedd to a specifique user.

    The whos are merged when a useraction sharing the same attributes with an
    unseen one is added. This is made in order to avoid having the same
    notification several times with only the who changing. It allows for more
    notifications shown at the same time."""

    id = schema.ASCIILine(title=u"ID")
    what = schema.ASCIILine(title=u"What")
    where = schema.ASCIILine(title=u"Where")
    when = schema.Datetime(title=u"When")
    who = schema.List(title=u"Who", value_type=schema.ASCIILine())
    gatherer = schema.ASCIILine(title=u"Gatherer")

    def getId():
        """Get the unique id of the notification"""

class Notification(object):
    interface.implements(INotification)

    def __init__(self, what, where, when, who, user):
        self.what = what
        self.where = where
        self.when = when
        self.who = who
        title = "%s" % self.when.strftime("%Y-%m-%d-%H-%M-%S")
        title += "-%s" % self.what.lower()
        title += "-%s" % self.where
        self.id = title

    def getId(self):
        return self.id
