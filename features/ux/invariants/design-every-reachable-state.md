# Design every state a user can reach

Empty, loading, partial, error and success are states of the surface, not accidents of the
data — each one gets a designed answer that says what happened and what the user can do next,
written before the surface ships. A screen, pane or command that only reads well once the data
is there is undesigned for the states a new user hits first. This holds wherever a human reads
the output: a rendered view, a terminal pane, or a command's stdout and stderr.
