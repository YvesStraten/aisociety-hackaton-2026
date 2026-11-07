"""One module per tab, plus the sidebar and shared charts.

Every tab module has a render(ctx) function made of numbered blocks. To change
a tab, edit one block function; to add something, write a new block function
and call it from render(). All data comes from FlatContext (data/context.py).
"""
