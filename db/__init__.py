"""Database access: connection, migrations, and the queries the pages run.

Everything here returns the plain dataclasses from lib.models, so no Streamlit
page ever handles a raw row and no logic module ever needs a connection.
"""
