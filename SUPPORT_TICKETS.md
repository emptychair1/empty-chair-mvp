# Trello support ticket setup

Empty Chair saves support tickets in its own database whether Trello is connected or not.

After creating a Trello board and a list for incoming tickets, add these environment variables in Render:

```text
TRELLO_API_KEY=your_trello_api_key
TRELLO_API_TOKEN=your_trello_api_token
TRELLO_SUPPORT_LIST_ID=the_destination_list_id
```

Redeploy the service after saving the variables.

New support tickets will then create cards in the selected list. Existing tickets with the status `PENDING_TRELLO` remain stored in Empty Chair; they are not automatically backfilled.
