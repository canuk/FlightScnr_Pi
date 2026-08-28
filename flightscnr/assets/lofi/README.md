# Lofi bed starter playlist

The starter tracks are original compositions by Reuben Thiessen
(CC BY-NC-SA 4.0, like the rest of the repository). They are too heavy
to live in git, so they ship as a zip attached to a GitHub Release and
install from the web portal: Settings → LoFi Beats → "Download starter
playlist". Tracks land in `/var/lib/flightscnr/lofi-pack/` and behave
like built-ins (play/disable, no remove).

Forks can point devices at their own pack with the `LOFI_PACK_URL`
environment variable (see `.env.example`).

Add your own MP3s on the device in `/var/lib/flightscnr/lofi/` — they
join the playlist automatically (alphabetical order).
