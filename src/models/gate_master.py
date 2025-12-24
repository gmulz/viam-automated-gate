from viam.services.generic import Generic
from viam.resource.easy_resource import EasyResource

class GateMaster(Generic, EasyResource):
    MODEL: ClassVar[Model] = Model(
        ModelFamily("grant-dev", "automated-gate"), "gate-master"
    )

    primary_gate_opener: Generic
    secondary_gate_opener: Generic

    