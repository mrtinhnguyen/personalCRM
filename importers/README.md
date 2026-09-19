# Importer contract

The existing WeChat, Instagram and LinkedIn collectors can emit the same batch
shape and submit it to `POST /api/v1/imports/batches`. An importer should keep
its own source cursor and send the last successful cursor as `cursor_before`.

Every record needs a stable `external_id` and a JSON-serializable `content`.
The API hashes canonical JSON and writes only a new content object when the
hash is new. Repeated records create a lightweight `source_observations` row
with `state=unchanged` and do not create a field revision or a media copy.

For posts and stories, add `entity_type: "post"` or `entity_type: "story"`,
the source `profile_id` once identity matching is confirmed, and
`occurred_at`. For a message stream, add `entity_type: "message"`,
`conversation_type`, `conversation_external_id`, `sender_profile_id`,
`message_type`, and `occurred_at`. These normalized fields let the API write
the correct projection while preserving the complete provider payload in the
raw manifest.

The collector can submit a prepared batch without importing an HTTP client:

```sh
python importers/submit_batch.py /path/to/batch.json \
  --api https://crm.example.ts.net \
  --secret "$WECHAT_IMPORT_SECRET" \
  --token "$WECHAT_IMPORT_TOKEN"
```

The token is optional while a source has no database-managed token. Once a
token is created in Import Center/API, every request for that source must send
the token; revoking it immediately blocks that collector without changing the
other sources.

Recommended import order: Monica/manual baseline, WeChat profiles/groups/messages/Moments,
Instagram profiles/posts/Story coverage, then LinkedIn profiles/work/education/posts.
Keep source archives outside Git. Submit uncertain matching decisions as identity
candidates and confirm them before associating a provider account with a person.
