# S Talking v0.20 Phase C

Phase C introduces persistent workspace profiles, a searchable Notification Center,
and a structured Activity Timeline. The existing ProductActivityService now acts as
the application event boundary and publishes to bounded persistent centers.

Built-in workspaces: Compact, Standard, Generation, Review, Debug, and Focus Mode.
Notification history is capped at 250 records and activity history at 500 records.
MainWindow only composes the independent widgets and records high-level generation events.
