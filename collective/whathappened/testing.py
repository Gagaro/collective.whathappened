from plone.app.testing import PloneSandboxLayer
from plone.app.testing import PLONE_FIXTURE
from plone.app.testing import IntegrationTesting, FunctionalTesting
from plone.app.robotframework.testing import AUTOLOGIN_LIBRARY_FIXTURE

from plone.testing import z2
from Testing.ZopeTestCase.utils import setupCoreSessions


class Layer(PloneSandboxLayer):

    defaultBases = (PLONE_FIXTURE,)

    def setUpZope(self, app, configurationContext):

        import collective.whathappened
        import collective.history
        self.loadZCML(package=collective.whathappened)
        self.loadZCML(package=collective.history)
        setupCoreSessions(app)

    def setUpPloneSite(self, portal):
        portal.portal_workflow.setDefaultChain('simple_publication_workflow')
        self.applyProfile(portal, 'collective.whathappened:default')


FIXTURE = Layer()
INTEGRATION = IntegrationTesting(bases=(FIXTURE,),
                                 name="collective.whathappened:Integration")
FUNCTIONAL = FunctionalTesting(bases=(FIXTURE,),
                               name="collective.whathappened:Functional")

ROBOT = FunctionalTesting(
    bases=(AUTOLOGIN_LIBRARY_FIXTURE, FIXTURE, z2.ZSERVER),
    name="collective.whathappened:Robot"
)
