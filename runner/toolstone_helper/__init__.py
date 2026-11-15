"""Toolstone helper app: runs fixed jobs (form fill, Vercel) on the user's own computer.

Everything the helper knows about the person (profile.json) and their keys (.env) stays in
~/.toolstone/ on this computer. Only job results (labels, deploy status) go to the relay.
"""
