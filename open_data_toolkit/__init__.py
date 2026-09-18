"""
The **GridPath Data Toolkit** creates GridPath scenario inputs from raw
data. It downloads public datasets — generator, balancing-authority, and
hourly-operations data published via `PUDL <https://catalyst.coop/pudl/>`__
and by the EIA — loads them into a raw data database, and processes them
into GridPath CSV input files: a project portfolio with capacities,
operating characteristics, fuels, and availability, plus load zones, fuel
prices, and a transmission topology, for a user-selected geographic
footprint, study year, and level of aggregation. Users may also provide
their own raw data and use the Toolkit to convert it to the GridPath CSV
input format for use in building a GridPath scenario database. See
:ref:`data-toolkit-workflow-section-ref` for the end-to-end workflow.
"""
