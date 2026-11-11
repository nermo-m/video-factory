# packages/adapters

Every external tool sits behind an adapter here: language model, image, clip, voice and
storage. Each adapter ships with a mock twin in the same pull request.

Rule: this is the only place a vendor SDK may be imported.

So far: `storage/` (local folder, the v1 storage) and `clip/probe.py` (is ComfyUI reachable).
