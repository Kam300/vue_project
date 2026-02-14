# Mobile API Cheat Sheet

Base URL (recommended):

`https://totalcode.indevs.in/api`

Legacy URL without `/api` also exists, but new clients should use `/api`.

## 1) Health check

- Method: `GET`
- URL: `/health`

Example:

```bash
curl -X GET "https://totalcode.indevs.in/api/health"
```

## 2) Register face

- Method: `POST`
- URL: `/register_face`
- Body:

```json
{
  "member_id": "1",
  "member_name": "Ivan",
  "image": "data:image/jpeg;base64,PASTE_BASE64_HERE"
}
```

Example:

```bash
curl -X POST "https://totalcode.indevs.in/api/register_face" \
  -H "Content-Type: application/json" \
  -d "{\"member_id\":\"1\",\"member_name\":\"Ivan\",\"image\":\"data:image/jpeg;base64,PASTE_BASE64_HERE\"}"
```

## 3) Recognize face

- Method: `POST`
- URL: `/recognize_face`
- Body:

```json
{
  "image": "data:image/jpeg;base64,PASTE_BASE64_HERE",
  "threshold": 0.6
}
```

Example:

```bash
curl -X POST "https://totalcode.indevs.in/api/recognize_face" \
  -H "Content-Type: application/json" \
  -d "{\"image\":\"data:image/jpeg;base64,PASTE_BASE64_HERE\",\"threshold\":0.6}"
```

## 4) List faces

- Method: `GET`
- URL: `/list_faces`

Example:

```bash
curl -X GET "https://totalcode.indevs.in/api/list_faces"
```

## 5) Delete face by member ID

- Method: `DELETE`
- URL: `/delete_face/{member_id}`

Example:

```bash
curl -X DELETE "https://totalcode.indevs.in/api/delete_face/1"
```

## 6) Clear all faces

- Method: `DELETE`
- URL: `/clear_all`

Example:

```bash
curl -X DELETE "https://totalcode.indevs.in/api/clear_all"
```

## 7) Generate PDF

- Method: `POST`
- URL: `/generate_pdf`
- Body (minimal):

```json
{
  "members": [
    {
      "id": "1",
      "firstName": "Ivan",
      "lastName": "Ivanov",
      "role": "FATHER"
    }
  ],
  "format": "A4_LANDSCAPE",
  "use_drive": true
}
```

Example:

```bash
curl -X POST "https://totalcode.indevs.in/api/generate_pdf" \
  -H "Content-Type: application/json" \
  -d "{\"members\":[{\"id\":\"1\",\"firstName\":\"Ivan\",\"lastName\":\"Ivanov\",\"role\":\"FATHER\"}],\"format\":\"A4_LANDSCAPE\",\"use_drive\":true}"
```

## 8) Download PDF by drive ID

- Method: `GET`
- URL: `/download_pdf/{drive_id}`

Example:

```bash
curl -L "https://totalcode.indevs.in/api/download_pdf/DRIVE_ID" -o family_tree.pdf
```

## Mobile client rules

- All POST requests must include header: `Content-Type: application/json`.
- `image` can be raw base64 or `data:image/...;base64,...` (both are accepted).
- Recommended flow:
  1. `GET /health`
  2. `POST /register_face` (once per person)
  3. `POST /recognize_face` (runtime recognition)
  4. `POST /generate_pdf` (when needed)
