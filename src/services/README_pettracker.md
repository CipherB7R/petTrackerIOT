After having defined the virtualization, AKA "DR consistency and synchronization with the server data" level, we move to the Service level.

The objects in these level are services, which are routines that take as input data and return a result.

The BaseService class defines the top of the hierarchy for the services class we may define.
It tells us a service must always implement the abstract method "execute(self, data: Dict, dr_type: str = None, attribute: str = None)".

In the original version of the NET4uCA framework, the BaseService class didn't impose any restriction on the type or content of data we supply to services (its description tells us it should be just a python's Dictionary),
but this is incorrect: we made it clear that the data Dict must be a dictionary of the form {"digital_replicas": data}, for the reasons
explained in the "A OOP convention violation" section.

In our version, a service is still "pluggable", in the sense we can add it to a DT to expand its functionalities (his "smartness"), but we need to
take into consideration that its argument "data" will always be a dictionary of the structure:

{"digital_replicas": data_of_all_dr_associated_to_dt_object_from_which_we_call_its__execute_service__method}.

#

Moving on, the services we have in this directory are both generalized and specialized in some way.

For the former type, we have the AggregationService, which serves as an example of how to write a service.

It requires the presence of the digital_replicas key in the data argument (As we mentioned earlier), and requires that all DRs have a 
"measurements" field in their "data" schema's section (otherwise he does nothing... its entire purpose is aggregating measurements, what did you expect?!).

Since the theory tells us a lot of DR in the IOT field may have the measurement field, it is reasonable to call this AggregationService "general", since
we may attach it to a lot of different DT types: in fact, we will associate it to each Door and Room DT!

For the latter type, we have our pet-tracking services, which require the presence of some field you will rarely see in other IOT applications.

In the following sections, you will read about the purposes of each file in this directory, minus the base.py and database_service.py which are self explanatory.

# analytics.py
This file contains many service definitions: they are all subclasses of the BaseService class that exposes the execute() method.

### AggregationService (subclass of BaseService)
This service has been defined by the Net4uCA framework.

It can be attached to all digital twins that aggregate DRs with a "measurements" data field.
We will attach this to each Room DT we create (remember, in our architecture each Door DT has a ONE TO ONE association with
its respective Door DR (nodeMCU device)).

# TODO: ADD more services specialized in our door, room and smart_home DTs!




# A OOP convention violation...

The NET4uCA framework implicitly defines a convention to pass data to services.

As we know, services should be objects that take as input DR data, maybe stored in a database, and return a result.

They may be specialized, I.E. some of them may work only with DRs that have a specific data field (like the "measurements" field for AggregationService),
but the previous statement remains true: **the input data to a service always contains DR data**.

This framework didn't make it clear in its BaseService definition, suggesting that services may take data in every form, and this led to confusion.

In particular, in this framework we always call services using the digital_twin level's objects, in particular using digital_twin/core.py's "execute_service()" method.

The problem is that, the DigitalTwin class is the base class for every DigitalTwin, so we are stuck to respect its definitions for reusability...

If you take a look at the code of that method, found in digital_twin/core.py file at line 37, we can see that it imposes a convention on the data Dictionary of the BaseService class:

_it must follow the {"digital_replicas": digital_replicas_data} structure._


**_This is a violation of the indipendency of levels, since we are retroactively fixing the format of service input!_**

We fixed this misunderstanding by fixing the format in the BaseService documentation.

This way, it looks like the DigitalTwin's execute_service() method was written to respect the (lower) service level's interface.