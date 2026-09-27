"""

import firebase_admin
from firebase_admin import credentials, firestore


# --------------------------------------------------
# Firebase
# --------------------------------------------------

cred = credentials.Certificate("serviceAccountKey.json")

firebase_admin.initialize_app(cred)

db = firestore.client()


# --------------------------------------------------
# Test users
# --------------------------------------------------

users = [
    "user1",
    "user2",
    "user3",
    "user4",
    "user5",
]


# --------------------------------------------------
# Test messages
# --------------------------------------------------

messages = [
    "Hey, how are you?",
    "Did you see my message?",
    "What are you doing today?",
    "Let me know when you're free.",
    "I wanted to ask you something.",
    "Are you available later?",
    "Hope you're having a good day.",
    "I'll talk to you later.",
    "Did you get my last message?",
    "Let me know what you think.",
    "That sounds good.",
    "I'll get back to you soon.",
    "Thanks for letting me know.",
    "Are you still coming?",
    "What time should we meet?",
    "I'll send you the details.",
    "Talk to you soon.",
    "Sounds good to me.",
    "Have a good night.",
    "See you tomorrow.",
]


# --------------------------------------------------
# Create messages
# --------------------------------------------------

batch = db.batch()

count = 0

for user_id in users:

    for text in messages:

        message_ref = (
            db
            .collection("users")
            .document(user_id)
            .collection("messages")
            .document()
        )

        batch.set(
            message_ref,
            {
                "userId": user_id,
                "text": text,
            },
        )

        count += 1


# --------------------------------------------------
# Commit
# --------------------------------------------------

batch.commit()

print(f"Successfully created {count} messages.")
"""