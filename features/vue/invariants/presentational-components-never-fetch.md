# Presentational components never fetch

Components below the route/view level communicate only through props in and events out — they
never import a store, call the API client, or fetch. Views (route targets) own async
orchestration and turn failures into user feedback; stores are the only layer that talks to the
API client. This keeps the component tree trivially testable and the data flow auditable in one
direction: view → store → API client → server.
