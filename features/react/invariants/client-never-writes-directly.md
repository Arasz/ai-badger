# Client never writes directly to the datastore

The frontend (and any other UI client) mutates state only by calling the backend API, never by talking to a database, storage account, or other datastore directly — even when the SDK would technically allow it. Authorization and validation live in exactly one place: the API.
