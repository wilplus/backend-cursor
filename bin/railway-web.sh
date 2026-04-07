#!/bin/sh
# Nixpacks puts ffmpeg in the Nix user profile; the default web process PATH often omits it.
export PATH="${HOME}/.nix-profile/bin:/root/.nix-profile/bin:/nix/var/nix/profiles/default/bin:${PATH}"
exec gunicorn app:app --bind "0.0.0.0:${PORT}" --workers 2 --timeout 120
