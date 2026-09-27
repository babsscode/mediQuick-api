from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional
import json
import os

import firebase_admin
from firebase_admin import credentials, auth, firestore

from pydantic import BaseModel, Field


from fastapi import (
    FastAPI,
    HTTPException,
    Header,
)

from fastapi.middleware.cors import CORSMiddleware

from pydantic import BaseModel, Field

from openai import OpenAI

from dotenv import load_dotenv


# ============================================================
# ENVIRONMENT
# ============================================================

load_dotenv()
key = os.getenv("OPENAI_API_KEY")

# ============================================================
# OPENAI
# ============================================================

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not OPENAI_API_KEY:
    raise RuntimeError(
        "OPENAI_API_KEY is not configured."
    )

openai_client = OpenAI(
    api_key=OPENAI_API_KEY
)


# ============================================================
# FASTAPI
# ============================================================

app = FastAPI(
    title="Impiricus API",
    version="1.0.0",
)


app.add_middleware(
    CORSMiddleware,

    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],

    allow_credentials=False,

    allow_methods=["*"],

    allow_headers=["*"],
)


# ============================================================
# FIREBASE
# ============================================================

SERVICE_ACCOUNT_FILE = Path(
    "serviceAccountKey.json"
)


if not SERVICE_ACCOUNT_FILE.exists():

    raise RuntimeError(
        "serviceAccountKey.json was not found."
    )


if not firebase_admin._apps:

    cred = credentials.Certificate(
        str(SERVICE_ACCOUNT_FILE)
    )

    firebase_admin.initialize_app(
        cred
    )


db = firestore.client()


# ============================================================
# HELPERS
# ============================================================

def utc_now():
    return datetime.now(
        timezone.utc
    )


def get_current_user(
    authorization: Optional[str],
):
    """
    Verify Firebase ID token and return decoded user.
    """

    if not authorization:

        raise HTTPException(
            status_code=401,
            detail="Authentication required.",
        )


    if not authorization.startswith(
        "Bearer "
    ):

        raise HTTPException(
            status_code=401,
            detail="Invalid authorization header.",
        )


    token = authorization.split(
        "Bearer ",
        1
    )[1].strip()


    if not token:

        raise HTTPException(
            status_code=401,
            detail="Authentication token missing.",
        )


    try:

        decoded_token = auth.verify_id_token(
            token
        )

        return decoded_token

    except Exception as error:

        print(
            "Firebase authentication failed:",
            error,
        )

        raise HTTPException(
            status_code=401,
            detail="Invalid or expired authentication token.",
        )


def get_user_profile(
    uid: str,
):
    """
    Get users/{uid} from Firestore.
    """

    user_ref = (
        db
        .collection("users")
        .document(uid)
    )

    snapshot = user_ref.get()


    if not snapshot.exists:

        return None


    return snapshot.to_dict()


def ensure_user_profile(
    firebase_user,
):
    """
    Make sure every authenticated Firebase user has
    a Firestore users/{uid} document.

    This is important because Firebase Authentication
    and Firestore are separate systems.
    """

    uid = firebase_user["uid"]

    user_ref = (
        db
        .collection("users")
        .document(uid)
    )

    snapshot = user_ref.get()


    if snapshot.exists:

        profile = snapshot.to_dict()

        # Make sure uid exists in the document.
        if not profile.get("uid"):

            user_ref.set(
                {
                    "uid": uid,
                    "updatedAt":
                        firestore.SERVER_TIMESTAMP,
                },
                merge=True,
            )

            profile["uid"] = uid


        return profile


    # --------------------------------------------------------
    # Firebase Auth data
    # --------------------------------------------------------

    name = (
        firebase_user.get("name")
        or firebase_user.get("display_name")
        or ""
    )

    email = (
        firebase_user.get("email")
        or ""
    )

    claims = firebase_user

    role = claims.get(
        "role",
        "hcp",
    )

    verified = claims.get(
        "verified",
        False,
    )


    # --------------------------------------------------------
    # Create Firestore profile
    # --------------------------------------------------------

    profile = {

        "uid":
            uid,

        "name":
            name,

        "email":
            email,

        "role":
            role,

        "verified":
            verified,

        # These can be completed by the profile UI.
        "specialty":
            "",

        "location":
            "",

        "about":
            "",

        "createdAt":
            firestore.SERVER_TIMESTAMP,

        "updatedAt":
            firestore.SERVER_TIMESTAMP,
    }


    user_ref.set(
        profile
    )


    # Return JSON-safe representation.
    return {
        "uid": uid,
        "name": name,
        "email": email,
        "role": role,
        "verified": verified,
        "specialty": "",
        "location": "",
        "about": "",
    }


# ============================================================
# HEALTH CHECK
# ============================================================

@app.get("/")
def root():

    return {
        "success": True,
        "service": "Impiricus API",
        "status": "running",
    }


@app.get("/health")
def health():

    return {
        "success": True,
        "status": "healthy",
    }


# ============================================================
# CURRENT USER
# ============================================================

@app.get("/auth/me")
def get_me(
    authorization: Optional[str] = Header(
        default=None
    ),
):

    firebase_user = get_current_user(
        authorization
    )


    profile = ensure_user_profile(
        firebase_user
    )


    return {
        "success": True,
        "user": profile,
    }


# ============================================================
# UPDATE CURRENT USER PROFILE
# ============================================================

class UpdateProfileRequest(BaseModel):

    name: Optional[str] = None

    specialty: Optional[str] = None

    location: Optional[str] = None

    about: Optional[str] = None


@app.patch("/auth/me")
def update_me(
    request: UpdateProfileRequest,

    authorization: Optional[str] = Header(
        default=None
    ),
):

    firebase_user = get_current_user(
        authorization
    )

    uid = firebase_user["uid"]


    # Make sure document exists first.
    existing = ensure_user_profile(
        firebase_user
    )


    update_data = {}


    if request.name is not None:

        update_data["name"] = (
            request.name.strip()
        )


    if request.specialty is not None:

        update_data["specialty"] = (
            request.specialty.strip()
        )


    if request.location is not None:

        update_data["location"] = (
            request.location.strip()
        )


    if request.about is not None:

        update_data["about"] = (
            request.about.strip()
        )


    update_data["updatedAt"] = (
        firestore.SERVER_TIMESTAMP
    )


    (
        db
        .collection("users")
        .document(uid)
        .set(
            update_data,
            merge=True,
        )
    )


    updated = get_user_profile(
        uid
    )


    return {
        "success": True,
        "user": updated,
    }


# ============================================================
# APPROVED USERS
# ============================================================

APPROVED_USERS_FILE = Path(
    "approved_users.json"
)


def load_approved_users():

    if not APPROVED_USERS_FILE.exists():

        return {}


    with open(
        APPROVED_USERS_FILE,
        "r",
    ) as file:

        return json.load(file)


# ============================================================
# REGISTRATION VERIFICATION
# ============================================================

class RegistrationVerification(BaseModel):

    name: str

    email: str

    role: str

    passcode: str = ""


@app.post(
    "/auth/verify-registration"
)
def verify_registration(
    request: RegistrationVerification,
):

    email = (
        request.email
        .strip()
        .lower()
    )

    role = (
        request.role
        .strip()
        .lower()
    )


    if role not in [
        "hcp",
        "pharma",
        "team_member",
    ]:

        raise HTTPException(
            status_code=400,
            detail="Invalid account type.",
        )


    # Team members do not require approval.
    if role == "team_member":

        return {
            "approved": True,
            "role": role,
            "verified": False,
        }


    approved_users = load_approved_users()

    approved_for_role = (
        approved_users.get(
            role,
            {},
        )
    )


    expected_passcode = (
        approved_for_role.get(
            email
        )
    )


    if expected_passcode is None:

        raise HTTPException(
            status_code=403,
            detail=(
                "This email is not approved "
                "for this account type."
            ),
        )


    if request.passcode != expected_passcode:

        raise HTTPException(
            status_code=403,
            detail=(
                "The verification passcode "
                "is incorrect."
            ),
        )


    return {
        "approved": True,
        "role": role,
        "verified": True,
    }


# ============================================================
# SET FIREBASE ROLE
# ============================================================

class SetUserRoleRequest(BaseModel):

    uid: str

    role: str

    verified: bool = False


@app.post(
    "/auth/set-role"
)
def set_user_role(
    request: SetUserRoleRequest,
):

    role = (
        request.role
        .strip()
        .lower()
    )


    if role not in [
        "hcp",
        "pharma",
        "team_member",
    ]:

        raise HTTPException(
            status_code=400,
            detail="Invalid role.",
        )


    try:

        auth.set_custom_user_claims(
            request.uid,
            {
                "role": role,
                "verified":
                    request.verified,
            },
        )


        user_ref = (
            db
            .collection("users")
            .document(request.uid)
        )


        user_ref.set(
            {
                "role": role,
                "verified":
                    request.verified,
                "updatedAt":
                    firestore.SERVER_TIMESTAMP,
            },
            merge=True,
        )


        return {
            "success": True,
            "uid": request.uid,
            "role": role,
            "verified":
                request.verified,
        }


    except Exception as error:

        print(
            "Failed to set role:",
            error,
        )

        raise HTTPException(
            status_code=500,
            detail="Unable to set user role.",
        )

# ============================================================
# SEED USERS
# ============================================================

@app.post("/seed")
def seed_users():

    seed_users_data = [
        {
            "name": "Dr. Sarah Johnson",
            "email": "doctor1@example.com",
            "password": "TestPassword123!",
            "role": "hcp",
            "verified": True,
            "location": "Clarksdale, MS",
            "specialty": "Cardiology",
            "about": "Cardiologist serving patients in a rural community with an interest in hypertension and heart failure management.",
            "interests": [
                "Resistant Hypertension",
                "Heart Failure",
                "Cardiovascular Prevention",
            ],
            "experience": [
                "Managed patients with treatment-resistant hypertension and heart failure.",
                "Experience treating patients with limited access to specialty care.",
            ],

            # ------------------------------------------------
            # Personalized SMS messages
            # ------------------------------------------------

            "messages": [
                {
                    "text": "New clinical resource: Practical considerations for managing resistant hypertension in patients taking multiple antihypertensive medications.",
                    "link": "https://www.heart.org/",
                },
                {
                    "text": "Cardiology update: New evidence and clinical perspectives on optimizing heart failure management in patients with persistent hypertension.",
                    "link": "https://www.acc.org/",
                },
                {
                    "text": "Resource for rural cardiology practice: Strategies for improving cardiovascular prevention and hypertension follow-up when specialty access is limited.",
                    "link": "https://www.cdc.gov/heart-disease/",
                },
                {
                    "text": "Clinical update: Review approaches to identifying and addressing common contributors to apparent treatment-resistant hypertension.",
                    "link": "https://www.ahajournals.org/",
                },
            ],
        },

        {
            "name": "Dr. Michael Smith",
            "email": "doctor2@example.com",
            "password": "TestPassword123!",
            "role": "hcp",
            "verified": True,
            "location": "Beckley, WV",
            "specialty": "Cardiology",
            "about": "Cardiologist practicing in a rural setting with a focus on complex hypertension and cardiovascular disease.",
            "interests": [
                "Resistant Hypertension",
                "Heart Failure",
                "Cardiovascular Disease",
            ],
            "experience": [
                "Experience managing treatment-resistant hypertension in patients with multiple comorbidities.",
                "Has worked with patients requiring adjustments to multi-drug antihypertensive regimens.",
            ],

            "messages": [
                {
                    "text": "Clinical resource: Review practical approaches to patients whose blood pressure remains uncontrolled despite multiple antihypertensive medications.",
                    "link": "https://www.acc.org/",
                },
                {
                    "text": "New cardiovascular resource: Evidence-based considerations for optimizing multi-drug antihypertensive regimens.",
                    "link": "https://www.heart.org/",
                },
                {
                    "text": "Heart failure update: Resources covering blood pressure management and cardiovascular risk reduction in patients with multiple comorbidities.",
                    "link": "https://www.heart.org/en/health-topics/heart-failure",
                },
                {
                    "text": "Practice update: Consider reviewing medication adherence, secondary causes, and measurement technique when evaluating apparent resistant hypertension.",
                    "link": "https://www.cdc.gov/high-blood-pressure/",
                },
            ],
        },

        {
            "name": "Dr. Emily Davis",
            "email": "doctor3@example.com",
            "password": "TestPassword123!",
            "role": "hcp",
            "verified": True,
            "location": "Waycross, GA",
            "specialty": "Cardiology",
            "about": "Cardiologist serving a rural patient population and interested in evidence-based approaches to difficult hypertension cases.",
            "interests": [
                "Hypertension",
                "Heart Failure",
                "Clinical Guidelines",
            ],
            "experience": [
                "Interested in treatment-resistant hypertension and complex cardiovascular cases.",
                "Looking for peer perspectives on managing patients who remain uncontrolled despite multiple medications.",
            ],

            "messages": [
                {
                    "text": "Clinical update: Review current evidence and guideline recommendations for patients with persistent hypertension despite treatment.",
                    "link": "https://www.heart.org/",
                },
                {
                    "text": "Cardiology resource: Practical strategies for evaluating uncontrolled hypertension and considering secondary causes.",
                    "link": "https://www.acc.org/",
                },
                {
                    "text": "New resource: Approaches to cardiovascular risk reduction in patients with hypertension and additional comorbidities.",
                    "link": "https://www.cdc.gov/heart-disease/",
                },
                {
                    "text": "Guideline reminder: Accurate blood-pressure measurement and medication adherence assessment remain important when evaluating uncontrolled hypertension.",
                    "link": "https://www.heart.org/en/health-topics/high-blood-pressure",
                },
            ],
        },

        {
            "name": "Dr. James Wilson",
            "email": "doctor4@example.com",
            "password": "TestPassword123!",
            "role": "hcp",
            "verified": True,
            "location": "New York, NY",
            "specialty": "Neurology",
            "about": "Neurologist focused on migraine treatment, epilepsy, and neurological disorders.",
            "interests": [
                "Migraine Treatment",
                "Epilepsy",
                "Neurological Disorders",
            ],
            "experience": [
                "Experience managing complex migraine cases.",
                "Interested in neurological clinical trials and treatment innovation.",
            ],

            "messages": [
                {
                    "text": "Neurology update: New clinical resources covering migraine prevention and treatment strategies.",
                    "link": "https://www.aan.com/",
                },
                {
                    "text": "Clinical resource: Review current approaches to identifying appropriate patients for preventive migraine therapy.",
                    "link": "https://americanmigrainefoundation.org/",
                },
                {
                    "text": "Neurology resource: Updates and educational materials covering seizure management and epilepsy care.",
                    "link": "https://www.aan.com/",
                },
                {
                    "text": "Research update: Explore current information on neurological clinical trials and emerging treatment approaches.",
                    "link": "https://clinicaltrials.gov/",
                },
            ],
        },

        {
            "name": "Alex Pharma",
            "email": "rep1@example.com",
            "password": "TestPassword123!",
            "role": "pharma",
            "verified": True,
            "location": "Boston, MA",
            "specialty": "Cardiology",
            "about": "Pharmaceutical representative supporting healthcare professionals with cardiovascular clinical resources and education.",

            "messages": [
                {
                    "text": "Cardiovascular resource update: New educational materials are available covering hypertension and cardiovascular risk management.",
                    "link": "https://www.acc.org/",
                },
                {
                    "text": "New resource: Review recent cardiovascular education and clinical updates relevant to hypertension management.",
                    "link": "https://www.heart.org/",
                },
            ],
        },

        {
            "name": "Taylor Pharma",
            "email": "rep2@example.com",
            "password": "TestPassword123!",
            "role": "pharma",
            "verified": True,
            "location": "San Francisco, CA",
            "specialty": "Oncology",
            "about": "Pharmaceutical representative focused on oncology therapies and educational resources.",

            "messages": [
                {
                    "text": "Oncology resource update: New educational materials covering current cancer treatment and supportive-care topics are available.",
                    "link": "https://www.cancer.gov/",
                },
                {
                    "text": "Clinical update: Explore current oncology resources and information on treatment innovation.",
                    "link": "https://www.asco.org/",
                },
            ],
        },
    ]


    users = []
    messages_created = 0


    # ========================================================
    # CREATE USERS
    # ========================================================

    for user_data in seed_users_data:

        try:

            firebase_user = auth.create_user(
                email=user_data["email"],
                password=user_data["password"],
                display_name=user_data["name"],
            )

        except auth.EmailAlreadyExistsError:

            firebase_user = auth.get_user_by_email(
                user_data["email"]
            )


        uid = firebase_user.uid


        # ----------------------------------------------------
        # Custom claims
        # ----------------------------------------------------

        auth.set_custom_user_claims(
            uid,
            {
                "role": user_data["role"],
                "verified": user_data["verified"],
            },
        )


        # ----------------------------------------------------
        # User profile
        # ----------------------------------------------------

        profile = {
            "uid": uid,

            "name": user_data["name"],

            "email": firebase_user.email,

            "role": user_data["role"],

            "verified": user_data["verified"],

            "location": user_data["location"],

            "specialty": user_data["specialty"],

            "about": user_data["about"],

            "updatedAt":
                firestore.SERVER_TIMESTAMP,
        }


        (
            db
            .collection("users")
            .document(uid)
            .set(
                profile,
                merge=True,
            )
        )


        # ====================================================
        # SEED SMS / USER MESSAGES
        #
        # Firestore:
        #
        # users/{uid}/messages/{messageId}
        # ====================================================

        messages_ref = (
            db
            .collection("users")
            .document(uid)
            .collection("messages")
        )


        existing_messages = list(
            messages_ref.limit(1).stream()
        )


        # Only seed messages if this user doesn't
        # already have any messages.
        #
        # This makes /seed safe to run multiple times.
        if not existing_messages:

            for index, message_data in enumerate(
                user_data.get("messages", [])
            ):

                message_ref = messages_ref.document()

                message_ref.set(
                    {
                        "userId": uid,

                        "text":
                            message_data["text"],

                        "link":
                            message_data.get(
                                "link"
                            ),

                        "type":
                            "resource",

                        "createdAt":
                            firestore.SERVER_TIMESTAMP,
                    }
                )

                messages_created += 1


        users.append(
            {
                "uid": uid,

                "name":
                    user_data["name"],

                "email":
                    firebase_user.email,

                "role":
                    user_data["role"],

                "verified":
                    user_data["verified"],

                "location":
                    user_data["location"],

                "specialty":
                    user_data["specialty"],

                "about":
                    user_data["about"],
            }
        )


    return {
        "success": True,

        "usersCreated":
            len(users),

        "messagesCreated":
            messages_created,

        "users":
            users,
    }


# ============================================================
# PEER MATCHING
# ============================================================

class PeerMatchingRequest(BaseModel):
    question: str
    specialty: str = ""
    location: str = ""
    about: str = ""


class PeerMatch(BaseModel):

    uid: str

    relevance_reason: str


@app.post(
    "/peer-connect/find-relevant-peers"
)
def find_relevant_peers(

    request: PeerMatchingRequest,

    authorization: Optional[str] = Header(
        default=None
    ),
):

    # --------------------------------------------------------
    # Authenticate
    # --------------------------------------------------------

    firebase_user = get_current_user(
        authorization
    )

    current_uid = (
        firebase_user["uid"]
    )


    # --------------------------------------------------------
    # Ensure current user's Firestore
    # profile exists.
    # --------------------------------------------------------

    current_profile = (
        ensure_user_profile(
            firebase_user
        )
    )


    question = (
        request.question.strip()
    )


    if not question:

        raise HTTPException(
            status_code=400,
            detail="Question is required.",
        )


    # ========================================================
    # GET HCP CANDIDATES
    # ========================================================

    user_documents = (
        db
        .collection("users")
        .where(
            "role",
            "==",
            "hcp",
        )
        .stream()
    )


    candidates = []


    for user_document in user_documents:

        user = (
            user_document.to_dict()
        )


        uid = user.get(
            "uid",
            user_document.id,
        )


        # Never match user to themselves.
        if uid == current_uid:

            continue


        candidates.append(
            {
                "uid":
                    uid,

                "name":
                    user.get(
                        "name",
                        "",
                    ),

                "location":
                    user.get(
                        "location",
                        "",
                    ),

                "specialty":
                    user.get(
                        "specialty",
                        "",
                    ),

                "about":
                    user.get(
                        "about",
                        "",
                    ),
            }
        )


    if not candidates:

        return {
            "success": True,
            "matches": [],
        }


    # ========================================================
    # PREPARE CANDIDATES
    # ========================================================

    candidate_text = "\n\n".join(

        (
            f"USER ID: {candidate['uid']}\n"
            f"NAME: {candidate['name']}\n"
            f"LOCATION: {candidate['location']}\n"
            f"SPECIALTY: {candidate['specialty']}\n"
            f"ABOUT: {candidate['about']}"
        )

        for candidate in candidates
    )


    current_specialty = (
        current_profile.get(
            "specialty",
            "",
        )
    )

    current_location = (
        current_profile.get(
            "location",
            "",
        )
    )

    current_about = (
        current_profile.get(
            "about",
            "",
        )
    )


    # ========================================================
    # OPENAI MATCHING
    # ========================================================

    try:

        response = (
            openai_client.responses.create(

                model="gpt-4.1-mini",

                input=[

                    {
                        "role":
                            "system",

                        "content":
                            """
You are a healthcare professional peer-matching system.

Your job is to identify the 1 or 2 HCPs from the supplied
candidate list who are most relevant to the requesting HCP's
clinical question.

Use the following signals:

1. Clinical relevance to the question.
2. Specialty relevance.
3. Clinical experience described in ABOUT.
4. Specific interests or expertise described in ABOUT.
5. Geographic/location similarity.

Clinical relevance and specialty should generally carry more
weight than geography.

Location should still be considered because peer-to-peer
discussion may benefit from similar regional practice
patterns.

Only select candidates from the supplied list.

Never invent a user.

Never select the requesting HCP.

Return at most 2 matches.

Return an empty list if there is no reasonably relevant HCP.

Return ONLY valid JSON:

{
  "matches": [
    {
      "uid": "candidate UID",
      "relevance_reason": "short explanation"
    }
  ]
}
""",
                    },

                    {
                        "role":
                            "user",

                        "content":
                            f"""
REQUESTING HCP

Specialty:
{current_specialty}

Location:
{current_location}

About:
{current_about}


CLINICAL QUESTION

{question}


CANDIDATE HCPs

{candidate_text}
""",
                    },
                ],
            )
        )


        raw_output = (
            response.output_text
        )


        result = json.loads(
            raw_output
        )


    except Exception as error:

        print(
            "OpenAI peer matching failed:",
            error,
        )

        raise HTTPException(
            status_code=500,
            detail=(
                "Unable to find relevant peers."
            ),
        )


    matches = result.get(
        "matches",
        [],
    )


    # ========================================================
    # VALIDATE AI OUTPUT AGAINST REAL USERS
    # ========================================================

    candidate_map = {
        candidate["uid"]:
            candidate
        for candidate in candidates
    }


    recommended_peers = []


    for match in matches:

        if not isinstance(
            match,
            dict,
        ):

            continue


        uid = match.get(
            "uid"
        )


        candidate = (
            candidate_map.get(uid)
        )


        if not candidate:

            continue


        recommended_peers.append(
            {
                "id":
                    candidate["uid"],

                "uid":
                    candidate["uid"],

                "name":
                    candidate["name"],

                "specialty":
                    candidate["specialty"],

                "location":
                    candidate["location"],

                "about":
                    candidate["about"],

                "bio":
                    candidate["about"],

                "relevanceReason":
                    match.get(
                        "relevance_reason",
                        "",
                    ),

                "interests":
                    [],
            }
        )


        if len(
            recommended_peers
        ) >= 2:

            break


    return {

        "success":
            True,

        "matches":
            recommended_peers,
    }


# ============================================================
# PEER REQUESTS
# ============================================================



class CreatePeerRequest(BaseModel):
    toUserId: str = Field(min_length=1)
    question: str = Field(min_length=1)
    title: str = Field(min_length=1)
    topics: list[str] = Field(default_factory=list)



@app.post("/peer-connect/requests")
def create_peer_request(
    request: CreatePeerRequest,
    authorization: str | None = Header(default=None),
):
    # --------------------------------------------------------
    # Authenticate current user
    # --------------------------------------------------------

    current_user = get_current_user(authorization)

    from_uid = current_user["uid"]

    # --------------------------------------------------------
    # Validate question
    # --------------------------------------------------------

    question = request.question.strip()
    title = request.title.strip()

    if not question:
        raise HTTPException(
            status_code=400,
            detail="Question is required.",
        )

    if not title:
        raise HTTPException(
            status_code=400,
            detail="Title is required.",
        )

    if from_uid == request.toUserId:
        raise HTTPException(
            status_code=400,
            detail="You cannot send a peer request to yourself.",
        )

    # --------------------------------------------------------
    # Get sender
    # --------------------------------------------------------

    sender_ref = (
        db
        .collection("users")
        .document(from_uid)
    )

    sender_snapshot = sender_ref.get()

    if not sender_snapshot.exists:
        raise HTTPException(
            status_code=404,
            detail=(
                "Your user profile was not found. "
                "Please complete your profile first."
            ),
        )

    sender = sender_snapshot.to_dict() or {}

    # --------------------------------------------------------
    # Get recipient
    # --------------------------------------------------------

    recipient_ref = (
        db
        .collection("users")
        .document(request.toUserId)
    )

    recipient_snapshot = recipient_ref.get()

    if not recipient_snapshot.exists:
        raise HTTPException(
            status_code=404,
            detail="The selected peer was not found.",
        )

    recipient = recipient_snapshot.to_dict() or {}

    if recipient.get("role") != "hcp":
        raise HTTPException(
            status_code=400,
            detail="Peer must be an HCP.",
        )

    # --------------------------------------------------------
    # Prevent duplicate pending request
    # --------------------------------------------------------

    existing_requests = (
        db
        .collection("peerRequests")
        .where("fromUserId", "==", from_uid)
        .where("toUserId", "==", request.toUserId)
        .where("status", "==", "pending")
        .stream()
    )

    for existing in existing_requests:
        raise HTTPException(
            status_code=409,
            detail="You already have a pending request with this peer.",
        )

    # --------------------------------------------------------
    # Create request
    # --------------------------------------------------------

    request_ref = (
        db
        .collection("peerRequests")
        .document()
    )

    request_data = {
        "fromUserId": from_uid,

        "fromUserName":
            sender.get("name", "Unknown User"),

        "toUserId":
            request.toUserId,

        "toUserName":
            recipient.get("name", "Unknown HCP"),

        "fromSpecialty":
            sender.get("specialty", ""),

        "fromLocation":
            sender.get("location", ""),

        "fromAbout":
            sender.get("about", ""),

        "title":
            title,

        "question":
            question,

        "topics":
            request.topics,

        "status":
            "pending",

        "createdAt":
            firestore.SERVER_TIMESTAMP,

        "updatedAt":
            firestore.SERVER_TIMESTAMP,
    }

    request_ref.set(request_data)

    return {
        "success": True,
        "requestId": request_ref.id,
        "status": "pending",
    }

# ============================================================
# GET PEER REQUESTS
# ============================================================
@app.get("/peer-connect/requests")
def get_peer_requests(
    authorization: str | None = Header(default=None),
):
    current_user = get_current_user(authorization)

    uid = current_user["uid"]

    # --------------------------------------------------------
    # Only requests sent TO this user
    # --------------------------------------------------------

    received = (
        db
        .collection("peerRequests")
        .where("toUserId", "==", uid)
        .stream()
    )

    requests = []

    for document in received:
        requests.append({
            "id": document.id,
            **document.to_dict(),
        })

    # Newest first.
    requests.sort(
        key=lambda item: (
            item.get("createdAt").timestamp()
            if item.get("createdAt")
            else 0
        ),
        reverse=True,
    )

    return {
        "success": True,
        "requests": requests,
    }
# ============================================================
# ACCEPT REQUEST
# ============================================================

@app.post(
    "/peer-connect/requests/{request_id}/accept"
)
def accept_peer_request(

    request_id: str,

    authorization: Optional[str] = Header(
        default=None
    ),
):

    firebase_user = get_current_user(
        authorization
    )

    uid = (
        firebase_user["uid"]
    )


    request_ref = (
        db
        .collection("peerRequests")
        .document(request_id)
    )


    request_snapshot = (
        request_ref.get()
    )


    if not request_snapshot.exists:

        raise HTTPException(
            status_code=404,
            detail="Request not found.",
        )


    request_data = (
        request_snapshot.to_dict()
    )


    if request_data.get(
        "toUserId"
    ) != uid:

        raise HTTPException(
            status_code=403,
            detail=(
                "You cannot accept this request."
            ),
        )


    if request_data.get(
        "status"
    ) != "pending":

        raise HTTPException(
            status_code=400,
            detail=(
                "This request is no longer pending."
            ),
        )


    # --------------------------------------------------------
    # Create conversation
    # --------------------------------------------------------

    conversation_ref = (
        db
        .collection(
            "peerConversations"
        )
        .document()
    )


    conversation_ref.set(
        {
            "participantIds": [
                request_data[
                    "fromUserId"
                ],
                request_data[
                    "toUserId"
                ],
            ],

            "title":
                request_data[
                    "title"
                ],

            "originalQuestion":
                request_data[
                    "question"
                ],

            "createdAt":
                firestore.SERVER_TIMESTAMP,

            "updatedAt":
                firestore.SERVER_TIMESTAMP,
        }
    )


    # --------------------------------------------------------
    # Update request
    # --------------------------------------------------------

    request_ref.update(
        {
            "status":
                "accepted",

            "conversationId":
                conversation_ref.id,

            "updatedAt":
                firestore.SERVER_TIMESTAMP,
        }
    )


    return {
    "success": True,
    "conversation": {
        "id": conversation_ref.id,
        "title": request_data.get("title", ""),
        "originalQuestion": request_data.get("question", ""),
        "doctorId": request_data["fromUserId"],
        "doctorName": request_data.get("fromUserName", ""),
        "specialty": request_data.get("specialty", ""),
        "location": request_data.get("location", ""),
        "messages": [],
    },
}


# ============================================================
# REJECT REQUEST
# ============================================================

@app.post(
    "/peer-connect/requests/{request_id}/reject"
)
def reject_peer_request(

    request_id: str,

    authorization: Optional[str] = Header(
        default=None
    ),
):

    firebase_user = get_current_user(
        authorization
    )

    uid = (
        firebase_user["uid"]
    )


    request_ref = (
        db
        .collection(
            "peerRequests"
        )
        .document(request_id)
    )


    snapshot = request_ref.get()


    if not snapshot.exists:

        raise HTTPException(
            status_code=404,
            detail="Request not found.",
        )


    data = snapshot.to_dict()


    if data.get(
        "toUserId"
    ) != uid:

        raise HTTPException(
            status_code=403,
            detail="Access denied.",
        )


    if data.get(
        "status"
    ) != "pending":

        raise HTTPException(
            status_code=400,
            detail="Request is no longer pending.",
        )


    request_ref.update(
        {
            "status":
                "rejected",

            "updatedAt":
                firestore.SERVER_TIMESTAMP,
        }
    )


    return {
        "success": True,
    }


# ============================================================
# GET CONVERSATIONS
# ============================================================

@app.get(
    "/peer-connect/conversations"
)
def get_conversations(

    authorization: Optional[str] = Header(
        default=None
    ),
):

    firebase_user = get_current_user(
        authorization
    )

    uid = firebase_user["uid"]


    # --------------------------------------------------------
    # Get conversations where current user is a participant
    # --------------------------------------------------------

    conversation_documents = (
        db
        .collection("peerConversations")
        .where(
            "participantIds",
            "array_contains",
            uid,
        )
        .stream()
    )


    conversations = []


    for document in conversation_documents:

        data = document.to_dict()


        # ----------------------------------------------------
        # Find the other participant
        # ----------------------------------------------------

        participant_ids = data.get(
            "participantIds",
            [],
        )


        other_user_id = None


        for participant_id in participant_ids:

            if participant_id != uid:

                other_user_id = participant_id

                break


        # ----------------------------------------------------
        # Get other user's profile
        # ----------------------------------------------------

        other_user = None


        if other_user_id:

            other_user = get_user_profile(
                other_user_id
            )


        # ----------------------------------------------------
        # Get messages
        #
        # Messages are stored at:
        #
        # peerConversations/{conversation_id}/messages
        # ----------------------------------------------------

        messages = []


        message_documents = (
            db
            .collection("peerConversations")
            .document(document.id)
            .collection("messages")
            .stream()
        )


        for message_document in message_documents:

            message_data = (
                message_document.to_dict()
            )


            messages.append(
                {
                    "id":
                        message_document.id,

                    "senderId":
                        message_data.get(
                            "senderId",
                            "",
                        ),

                    "senderName":
                        message_data.get(
                            "senderName",
                        ),

                    "text":
                        message_data.get(
                            "text",
                            message_data.get(
                                "message",
                                "",
                            ),
                        ),

                    "createdAt":
                        message_data.get(
                            "createdAt",
                        ),
                }
            )


        # ----------------------------------------------------
        # Sort messages oldest -> newest
        # ----------------------------------------------------

        messages.sort(
            key=lambda message: (
                message.get(
                    "createdAt"
                ).timestamp()
                if message.get(
                    "createdAt"
                )
                else 0
            )
        )


        # ----------------------------------------------------
        # Build conversation
        # ----------------------------------------------------

        conversations.append(
            {
                "id":
                    document.id,

                "title":
                    data.get(
                        "title",
                        "",
                    ),

                "originalQuestion":
                    data.get(
                        "originalQuestion",
                        "",
                    ),

                "doctorId":
                    other_user_id,

                "doctorName":
                    (
                        other_user.get(
                            "name",
                            "",
                        )
                        if other_user
                        else ""
                    ),

                "specialty":
                    (
                        other_user.get(
                            "specialty",
                            "",
                        )
                        if other_user
                        else ""
                    ),

                "location":
                    (
                        other_user.get(
                            "location",
                            "",
                        )
                        if other_user
                        else ""
                    ),

                "messages":
                    messages,

                "createdAt":
                    data.get(
                        "createdAt"
                    ),

                "updatedAt":
                    data.get(
                        "updatedAt"
                    ),
            }
        )


    # --------------------------------------------------------
    # Sort conversations newest/most recently updated first
    # --------------------------------------------------------

    conversations.sort(
        key=lambda conversation: (
            conversation.get(
                "updatedAt"
            ).timestamp()
            if conversation.get(
                "updatedAt"
            )
            else 0
        ),
        reverse=True,
    )


    return {

        "success":
            True,

        "conversations":
            conversations,
    }


# ============================================================
# SEND MESSAGE
# ============================================================

class SendPeerMessage(BaseModel):

    text: str

@app.post(
    "/peer-connect/conversations/{conversation_id}/messages"
)
def send_peer_message(

    conversation_id: str,

    request: SendPeerMessage,

    authorization: Optional[str] = Header(
        default=None
    ),
):

    firebase_user = get_current_user(
        authorization
    )

    uid = firebase_user["uid"]


    # --------------------------------------------------------
    # Validate message
    # --------------------------------------------------------

    text = request.text.strip()


    if not text:

        raise HTTPException(
            status_code=400,
            detail="Message cannot be empty.",
        )


    # --------------------------------------------------------
    # Get conversation
    # --------------------------------------------------------

    conversation_ref = (
        db
        .collection("peerConversations")
        .document(conversation_id)
    )


    conversation_snapshot = (
        conversation_ref.get()
    )


    if not conversation_snapshot.exists:

        raise HTTPException(
            status_code=404,
            detail="Conversation not found.",
        )


    conversation = (
        conversation_snapshot.to_dict()
    )


    # --------------------------------------------------------
    # Verify current user is a participant
    # --------------------------------------------------------

    if uid not in conversation.get(
        "participantIds",
        [],
    ):

        raise HTTPException(
            status_code=403,
            detail=(
                "You are not part of this conversation."
            ),
        )


    # --------------------------------------------------------
    # Get sender profile
    # --------------------------------------------------------

    sender_profile = get_user_profile(uid)


    sender_name = (
        sender_profile.get("name", "")
        if sender_profile
        else ""
    )


    # --------------------------------------------------------
    # Create message
    # --------------------------------------------------------

    message_ref = (
        conversation_ref
        .collection("messages")
        .document()
    )


    message_ref.set(
        {
            "senderId":
                uid,

            "senderName":
                sender_name,

            "text":
                text,

            "type":
                "text",

            "createdAt":
                firestore.SERVER_TIMESTAMP,
        }
    )


    # --------------------------------------------------------
    # Update conversation timestamp
    # --------------------------------------------------------

    conversation_ref.update(
        {
            "updatedAt":
                firestore.SERVER_TIMESTAMP,
        }
    )


    # --------------------------------------------------------
    # Return message
    #
    # IMPORTANT:
    # The React frontend expects response.message.
    #
    # SERVER_TIMESTAMP does not immediately give us a normal
    # Python timestamp, so use the current UTC time for the
    # response object.
    # --------------------------------------------------------

    from datetime import datetime, timezone

    created_at = datetime.now(
        timezone.utc
    )


    return {

        "success":
            True,

        "message": {

            "id":
                message_ref.id,

            "senderId":
                uid,

            "senderName":
                sender_name,

            "text":
                text,

            "type":
                "text",

            "createdAt":
                created_at.isoformat(),
        },
    }


# ============================================================
# GET MESSAGES
# ============================================================

@app.get(
    "/peer-connect/conversations/{conversation_id}/messages"
)
def get_messages(

    conversation_id: str,

    authorization: Optional[str] = Header(
        default=None
    ),
):

    firebase_user = get_current_user(
        authorization
    )

    uid = (
        firebase_user["uid"]
    )


    conversation_ref = (
        db
        .collection(
            "peerConversations"
        )
        .document(
            conversation_id
        )
    )


    conversation_snapshot = (
        conversation_ref.get()
    )


    if not conversation_snapshot.exists:

        raise HTTPException(
            status_code=404,
            detail="Conversation not found.",
        )


    conversation = (
        conversation_snapshot.to_dict()
    )


    if uid not in conversation.get(
        "participantIds",
        [],
    ):

        raise HTTPException(
            status_code=403,
            detail="Access denied.",
        )


    message_documents = (
        conversation_ref
        .collection("messages")
        .order_by("createdAt")
        .stream()
    )


    messages = []


    for message_document in message_documents:

        data = (
            message_document.to_dict()
        )


        sender_id = (
            data.get(
                "senderId"
            )
        )


        messages.append(
            {
                "id":
                    message_document.id,

                "senderId":
                    sender_id,

                "text":
                    data.get(
                        "text",
                        "",
                    ),

                "type":
                    data.get(
                        "type",
                        "text",
                    ),

                "sender":
                    (
                        "me"
                        if sender_id == uid
                        else "peer"
                    ),

                "createdAt":
                    data.get(
                        "createdAt"
                    ),
            }
        )


    return {

        "success":
            True,

        "messages":
            messages,
    }




@app.post("/seed/discussions")
def seed_discussions():

    print("🔥 /seed/discussions HIT", flush=True)

    # --------------------------------------------------------
    # Make sure the HCP seed users exist.
    # --------------------------------------------------------

    hcp_users = []

    for email in [
        "doctor1@example.com",
        "doctor2@example.com",
        "doctor3@example.com",
        "doctor4@example.com",
    ]:

        try:

            user = auth.get_user_by_email(email)

            print(
                f"Found seed user {email}: {user.uid}",
                flush=True,
            )

            hcp_users.append(user)

        except Exception as error:

            print(
                f"Could not find seed user {email}: {error}",
                flush=True,
            )

    if not hcp_users:

        raise HTTPException(
            status_code=400,
            detail=(
                "No HCP seed users found. "
                "Run /seed first."
            ),
        )

    # --------------------------------------------------------
    # Discussion seed data
    # --------------------------------------------------------

    discussions = [

        {
            "title":
                "Managing treatment-resistant hypertension despite multiple medications",

            "description":
                "How are other cardiologists managing patients with treatment-resistant hypertension who remain uncontrolled despite multiple medications? Share clinical experiences, approaches to multi-drug antihypertensive regimens, and strategies for difficult-to-control cases.",

            "specialty":
                "Cardiology",

            "popular":
                True,

            "messages": [

                {
                    "anonymousName":
                        "Anonymous 1",

                    "role":
                        "hcp",

                    "text":
                        "I have seen this fairly often in patients taking three or more agents. Before adding another medication, I usually revisit adherence, dosing schedules, and whether there may be a secondary cause contributing to the persistent elevation.",

                    "parentMessageId":
                        None,
                },

                {
                    "anonymousName":
                        "Anonymous 2",

                    "role":
                        "hcp",

                    "text":
                        "Agreed. I also find that reviewing home blood pressure readings can change the picture considerably. White-coat effect and inconsistent measurement technique can make an apparently resistant case look different.",

                    "parentMessageId":
                        None,
                },

                {
                    "anonymousName":
                        "Anonymous 3",

                    "role":
                        "hcp",

                    "text":
                        "For patients who truly remain uncontrolled, I have had useful discussions with nephrology about secondary hypertension and medication optimization. The patient's renal function and potassium trends are particularly important when adjusting the regimen.",

                    "parentMessageId":
                        None,
                },

                {
                    "anonymousName":
                        "Anonymous 4",

                    "role":
                        "hcp",

                    "text":
                        "One practical challenge in rural practice is access to follow-up and specialty consultation. Simplifying the regimen where possible has sometimes been just as important as adding another medication.",

                    "parentMessageId":
                        None,
                },

                {
                    "anonymousName":
                        "Example Pharma Representative",

                    "role":
                        "pharma",

                    "company":
                        "Example Pharma",

                    "text":
                        "Thank you for the thoughtful discussion. Our medical information team can provide the approved prescribing information and clinical resources for healthcare professionals who would like to review the available evidence around treatment options.",

                    "parentMessageId":
                        None,
                },
            ],
        },

        {
            "title":
                "Approaches to uncontrolled hypertension in complex patients",

            "description":
                "Discuss experiences managing patients whose blood pressure remains uncontrolled despite multiple antihypertensive medications, including patients with multiple comorbidities.",

            "specialty":
                "Cardiology",

            "popular":
                True,

            "messages": [

                {
                    "anonymousName":
                        "Anonymous 1",

                    "role":
                        "hcp",

                    "text":
                        "In complex patients, I try to look at the entire medication list rather than treating the blood pressure number in isolation. NSAID use, adherence, dosing intervals, and other medications can all be relevant.",

                    "parentMessageId":
                        None,
                },

                {
                    "anonymousName":
                        "Anonymous 2",

                    "role":
                        "hcp",

                    "text":
                        "I have also found it helpful to ask patients to bring all of their medications to the visit. It occasionally uncovers duplicate therapies, medications being taken differently than prescribed, or confusion about dosing.",

                    "parentMessageId":
                        None,
                },

                {
                    "anonymousName":
                        "Anonymous 3",

                    "role":
                        "hcp",

                    "text":
                        "When there are multiple comorbidities, I think the treatment plan needs to account for renal function, electrolyte abnormalities, heart failure status, and tolerability rather than simply adding agents sequentially.",

                    "parentMessageId":
                        None,
                },

                {
                    "anonymousName":
                        "Example Pharma Representative",

                    "role":
                        "pharma",

                    "company":
                        "Example Pharma",

                    "text":
                        "For healthcare professionals looking for product-specific information, please refer to the current approved prescribing information or contact the appropriate medical information department.",

                    "parentMessageId":
                        None,
                },
            ],
        },

        {
            "title":
                "Treatment-resistant hypertension and heart failure",

            "description":
                "Share clinical perspectives on managing treatment-resistant hypertension in patients with heart failure and other cardiovascular comorbidities.",

            "specialty":
                "Cardiology",

            "popular":
                True,

            "messages": [

                {
                    "anonymousName":
                        "Anonymous 1",

                    "role":
                        "hcp",

                    "text":
                        "The combination of hypertension and heart failure can make medication decisions particularly challenging. I usually consider volume status, renal function, potassium, and the patient's overall tolerance before making changes.",

                    "parentMessageId":
                        None,
                },

                {
                    "anonymousName":
                        "Anonymous 2",

                    "role":
                        "hcp",

                    "text":
                        "I agree. Follow-up labs have been especially important for some of my patients after medication changes. The clinical response and laboratory response do not always move together.",

                    "parentMessageId":
                        None,
                },

                {
                    "anonymousName":
                        "Anonymous 3",

                    "role":
                        "hcp",

                    "text":
                        "Another issue is making sure the patient understands why multiple medications may be necessary. I have had better adherence when I explain the purpose of each medication rather than presenting the regimen as simply another list of pills.",

                    "parentMessageId":
                        None,
                },

                {
                    "anonymousName":
                        "Anonymous 4",

                    "role":
                        "hcp",

                    "text":
                        "For patients with frequent admissions or worsening symptoms, coordination between primary care, cardiology, and other specialists can make a substantial difference in keeping the treatment plan consistent.",

                    "parentMessageId":
                        None,
                },
            ],
        },

        {
            "title":
                "Managing difficult hypertension cases in rural practice",

            "description":
                "Discuss challenges and approaches to managing difficult-to-control hypertension in rural patient populations, including patients with limited access to specialty care.",

            "specialty":
                "Cardiology",

            "popular":
                False,

            "messages": [

                {
                    "anonymousName":
                        "Anonymous 1",

                    "role":
                        "hcp",

                    "text":
                        "Limited access to specialty care can make difficult hypertension cases particularly challenging. I often try to make the initial workup as comprehensive as practical before referring the patient.",

                    "parentMessageId":
                        None,
                },

                {
                    "anonymousName":
                        "Anonymous 2",

                    "role":
                        "hcp",

                    "text":
                        "Telehealth consultation has helped in some cases, although transportation and broadband access can still be barriers for certain patients.",

                    "parentMessageId":
                        None,
                },

                {
                    "anonymousName":
                        "Anonymous 3",

                    "role":
                        "hcp",

                    "text":
                        "Medication affordability is another issue that comes up frequently. A theoretically ideal regimen is not useful if the patient cannot consistently obtain the medications.",

                    "parentMessageId":
                        None,
                },
            ],
        },

        {
            "title":
                "Clinical approaches to hypertension management",

            "description":
                "Share evidence-based approaches, clinical guidelines, and practical experiences for managing patients with persistent hypertension.",

            "specialty":
                "Cardiology",

            "popular":
                False,

            "messages": [

                {
                    "anonymousName":
                        "Anonymous 1",

                    "role":
                        "hcp",

                    "text":
                        "I find these discussions useful because the practical challenges often differ from what is described in a guideline. Patient adherence, access, side effects, and follow-up all influence the final treatment plan.",

                    "parentMessageId":
                        None,
                },

                {
                    "anonymousName":
                        "Anonymous 2",

                    "role":
                        "hcp",

                    "text":
                        "Home monitoring has become a major part of my approach. Having several readings over time is often more informative than relying on a single office measurement.",

                    "parentMessageId":
                        None,
                },

                {
                    "anonymousName":
                        "Anonymous 3",

                    "role":
                        "hcp",

                    "text":
                        "I also encourage reviewing the diagnosis periodically when the clinical picture does not fit. Persistent hypertension can sometimes prompt a broader evaluation rather than simply escalating treatment.",

                    "parentMessageId":
                        None,
                },

                {
                    "anonymousName":
                        "Example Pharma Representative",

                    "role":
                        "pharma",

                    "company":
                        "Example Pharma",

                    "text":
                        "We appreciate the discussion. Healthcare professionals can consult the applicable approved product information and medical information resources for questions about specific therapies.",

                    "parentMessageId":
                        None,
                },
            ],
        },
    ]

    # --------------------------------------------------------
    # Create discussions and messages
    # --------------------------------------------------------

    created_discussions = []
    created_messages = []

    try:

        for discussion_data in discussions:

            print(
                f"Creating discussion: "
                f"{discussion_data['title']}",
                flush=True,
            )

            # ------------------------------------------------
            # Discussion document
            # ------------------------------------------------

            discussion_ref = (
                db
                .collection("discussions")
                .document()
            )

            discussion_id = discussion_ref.id

            message_seed_data = (
                discussion_data.get(
                    "messages",
                    [],
                )
            )

            # ------------------------------------------------
            # Count unique HCP participants
            # ------------------------------------------------

            hcp_anonymous_names = set()

            for message in message_seed_data:

                if message.get("role") == "hcp":

                    hcp_anonymous_names.add(
                        message.get(
                            "anonymousName",
                            "Anonymous HCP",
                        )
                    )

            participant_count = len(
                hcp_anonymous_names
            )

            # ------------------------------------------------
            # Write discussion
            # ------------------------------------------------

            discussion_ref.set(
                {
                    "title":
                        discussion_data["title"],

                    "description":
                        discussion_data["description"],

                    "specialty":
                        discussion_data["specialty"],

                    "participantCount":
                        participant_count,

                    "popular":
                        discussion_data["popular"],

                    "source":
                        "seed",
                }
            )

            print(
                f"✅ Discussion created: {discussion_id}",
                flush=True,
            )

            created_discussions.append(
                {
                    "id":
                        discussion_id,

                    "title":
                        discussion_data["title"],

                    "participantCount":
                        participant_count,

                    "messages":
                        len(message_seed_data),
                }
            )

            # ------------------------------------------------
            # Messages subcollection
            # ------------------------------------------------

            messages_ref = (
                discussion_ref
                .collection("messages")
            )

            for index, message_data in enumerate(
                message_seed_data
            ):

                message_ref = (
                    messages_ref.document()
                )

                role = message_data.get(
                    "role",
                    "hcp",
                )

                message_payload = {

                    "authorId":
                        (
                            "seed-pharma"
                            if role == "pharma"
                            else (
                                "seed-hcp-"
                                + str(index + 1)
                            )
                        ),

                    "text":
                        message_data["text"],

                    "role":
                        role,

                    "anonymousName":
                        message_data.get(
                            "anonymousName",
                            "Anonymous HCP",
                        ),

                    "verified":
                        True,

                    "parentMessageId":
                        message_data.get(
                            "parentMessageId"
                        ),
                }

                if role == "pharma":

                    message_payload["company"] = (
                        message_data.get(
                            "company",
                            "Example Pharma",
                        )
                    )

                message_ref.set(
                    message_payload
                )

                created_messages.append(
                    {
                        "discussionId":
                            discussion_id,

                        "messageId":
                            message_ref.id,

                        "anonymousName":
                            message_payload[
                                "anonymousName"
                            ],

                        "role":
                            message_payload[
                                "role"
                            ],
                    }
                )

                print(
                    f"  ✅ Message created: "
                    f"{message_ref.id}",
                    flush=True,
                )

        # ----------------------------------------------------
        # Success
        # ----------------------------------------------------

        print(
            "🎉 SEED DISCUSSIONS COMPLETED",
            flush=True,
        )

        return {

            "success":
                True,

            "message":
                "Seed discussions and messages created successfully.",

            "discussionsCreated":
                len(created_discussions),

            "messagesCreated":
                len(created_messages),

            "discussions":
                created_discussions,
        }

    except Exception as error:

        print(
            "❌ Failed to seed discussions:",
            repr(error),
            flush=True,
        )

        raise HTTPException(
            status_code=500,
            detail=(
                f"Failed to seed discussions: "
                f"{str(error)}"
            ),
        )

# ============================================================
# SEARCH
# ============================================================

class SearchRequest(BaseModel):
    query: str = Field(min_length=1)
    limit: int = Field(default=10, ge=1, le=20)


def serialize_firestore_value(value):
    """
    Convert Firestore timestamps and other common values into
    JSON-safe values.
    """

    if value is None:
        return None

    if isinstance(value, datetime):
        return value.isoformat()

    return value


def rank_search_results(
    query: str,
    candidates: list[dict],
    result_type: str,
    limit: int,
):
    """
    Use OpenAI to semantically rank Firestore search results.

    The model is only allowed to return IDs supplied in
    candidates.
    """

    if not candidates:
        return []

    # Keep the prompt reasonably small.
    candidate_text = "\n\n".join(
        (
            f"ID: {item['id']}\n"
            f"CONTENT: {item.get('searchText', '')}"
        )
        for item in candidates
    )

    try:
        response = openai_client.responses.create(
            model="gpt-4.1-mini",

            input=[
                {
                    "role": "system",
                    "content": f"""
You are a semantic search ranking system.

The user entered a search query and we need to find the most
relevant {result_type}.

Rank the supplied candidates according to how relevant they
are to the user's search query.

Consider:
- Meaning and intent
- Clinical topic relevance
- Important concepts and terminology
- Closely related clinical subjects
- Synonyms and related terminology

Do NOT invent candidates.

Only return IDs that appear in the supplied candidate list.

Return at most {limit} results.

If nothing is reasonably relevant, return an empty list.

Return ONLY valid JSON in this format:

{{
  "results": [
    {{
      "id": "candidate ID",
      "relevance_reason": "short explanation"
    }}
  ]
}}
""",
                },
                {
                    "role": "user",
                    "content": f"""
SEARCH QUERY:

{query}


CANDIDATES:

{candidate_text}
""",
                },
            ],
        )

        raw_output = response.output_text

        result = json.loads(raw_output)

        ranked_results = result.get(
            "results",
            [],
        )

    except Exception as error:

        print(
            "OpenAI search ranking failed:",
            error,
            flush=True,
        )

        # ----------------------------------------------------
        # Fallback to simple text matching.
        #
        # This means the endpoint still works if OpenAI
        # ranking temporarily fails.
        # ----------------------------------------------------

        query_words = set(
            query.lower().split()
        )

        scored = []

        for candidate in candidates:

            content = candidate.get(
                "searchText",
                "",
            ).lower()

            score = sum(
                1
                for word in query_words
                if word in content
            )

            if score > 0:
                scored.append(
                    (
                        score,
                        candidate["id"],
                    )
                )

        scored.sort(
            reverse=True
        )

        ranked_results = [
            {
                "id": item_id,
                "relevance_reason":
                    "Matched terms in the search query.",
            }
            for _, item_id in scored[:limit]
        ]

    # --------------------------------------------------------
    # Validate OpenAI IDs against real Firestore documents.
    # --------------------------------------------------------

    candidate_map = {
        item["id"]: item
        for item in candidates
    }

    results = []

    for ranked in ranked_results:

        if not isinstance(
            ranked,
            dict,
        ):
            continue

        item_id = ranked.get("id")

        candidate = candidate_map.get(
            item_id
        )

        if not candidate:
            continue

        result = {
            key: value
            for key, value in candidate.items()
            if key != "searchText"
        }

        result["relevanceReason"] = (
            ranked.get(
                "relevance_reason",
                "",
            )
        )

        results.append(result)

        if len(results) >= limit:
            break

    return results
# ============================================================
# SEARCH USER MESSAGES / SMS + RESOURCES
# ============================================================

@app.post("/messages/search")
def search_user_messages(
    request: SearchRequest,
    authorization: Optional[str] = Header(
        default=None
    ),
):
    """
    AI-assisted search for:

    1. The currently authenticated user's SMS/messages.
    2. Global resources available in the Resources page.

    The user's messages remain strictly user-scoped.

    The resources below mirror the resources currently
    displayed in Sms.tsx.
    """

    # --------------------------------------------------------
    # Authenticate user
    # --------------------------------------------------------

    firebase_user = get_current_user(
        authorization
    )

    uid = firebase_user["uid"]

    query = request.query.strip()

    if not query:
        raise HTTPException(
            status_code=400,
            detail="Search query is required.",
        )

    # ========================================================
    # 1. USER SMS / MESSAGES
    # ========================================================

    message_documents = (
        db
        .collection("users")
        .document(uid)
        .collection("messages")
        .stream()
    )

    candidates = []

    for document in message_documents:

        data = document.to_dict() or {}

        text = data.get(
            "text",
            "",
        )

        link = data.get(
            "link",
            "",
        )

        message_type = data.get(
            "type",
            "resource",
        )

        search_text = (
            f"Message: {text}\n"
            f"Type: {message_type}\n"
            f"Link: {link}"
        )

        candidates.append(
            {
                "id": document.id,

                "resultType": "sms",

                "text": text,

                "link": link,

                "type": message_type,

                "createdAt":
                    serialize_firestore_value(
                        data.get(
                            "createdAt"
                        )
                    ),

                "searchText": search_text,
            }
        )

    # ========================================================
    # 2. RESOURCES
    #
    # These match the resources currently in Sms.tsx.
    # ========================================================

    resources = [
        {
            "id": "resource-1",
            "title": "Treatment-Resistant Hypertension Guide",
            "description":
                "A clinical guide covering treatment considerations for patients whose blood pressure remains uncontrolled despite multiple therapies.",
            "topic": "Hypertension",
            "category": "Clinical Guide",
            "date": "Sep 24, 2026",
        },
        {
            "id": "resource-2",
            "title": "Heart Failure Treatment Overview",
            "description":
                "An overview of current approaches to heart failure treatment, monitoring, and treatment sequencing.",
            "topic": "Heart Failure",
            "category": "Clinical Resource",
            "date": "Sep 23, 2026",
        },
        {
            "id": "resource-3",
            "title": "Cardiovascular Clinical Trials Directory",
            "description":
                "Browse ongoing cardiovascular clinical trials and explore study information and eligibility criteria.",
            "topic": "Clinical Trials",
            "category": "Clinical Trials",
            "date": "Sep 21, 2026",
        },
        {
            "id": "resource-4",
            "title": "Patient Access & Coverage Guide",
            "description":
                "Information designed to help HCPs navigate common patient access, coverage, and insurance questions.",
            "topic": "Patient Access",
            "category": "Patient Support",
            "date": "Sep 20, 2026",
        },
        {
            "id": "resource-5",
            "title": "ACE Inhibitor Reference",
            "description":
                "Reference material covering ACE inhibitors, their clinical use, and cardiovascular treatment considerations.",
            "topic": "ACE Inhibitors",
            "category": "Reference",
            "date": "Sep 18, 2026",
        },
        {
            "id": "resource-6",
            "title": "Diabetes & Cardiovascular Health",
            "description":
                "Educational material exploring cardiovascular considerations when managing patients with diabetes.",
            "topic": "Diabetes",
            "category": "Educational Resource",
            "date": "Sep 17, 2026",
        },
        {
            "id": "resource-7",
            "title": "Hypertension Patient Discussion Guide",
            "description":
                "A patient-facing resource designed to support conversations about blood pressure goals and treatment.",
            "topic": "Hypertension",
            "category": "Patient Resource",
            "date": "Sep 15, 2026",
        },
        {
            "id": "resource-8",
            "title": "Heart Failure Monitoring Checklist",
            "description":
                "A practical reference for monitoring patients with heart failure during ongoing treatment.",
            "topic": "Heart Failure",
            "category": "Clinical Tool",
            "date": "Sep 13, 2026",
        },
        {
            "id": "resource-9",
            "title": "Cardiovascular Prevention Reference",
            "description":
                "A reference covering cardiovascular risk factors, prevention strategies, and patient conversations.",
            "topic": "Cardiology",
            "category": "Reference",
            "date": "Sep 11, 2026",
        },
        {
            "id": "resource-10",
            "title": "Specialist Referral & Care Coordination",
            "description":
                "Resources for coordinating care between primary care providers and cardiovascular specialists.",
            "topic": "Care Coordination",
            "category": "Practice Resource",
            "date": "Sep 9, 2026",
        },
        {
            "id": "resource-11",
            "title": "Blood Pressure Monitoring Guide",
            "description":
                "A practical guide to monitoring blood pressure and identifying patterns that may require additional evaluation.",
            "topic": "Hypertension",
            "category": "Clinical Tool",
            "date": "Sep 8, 2026",
        },
        {
            "id": "resource-12",
            "title": "Cardiac Risk Assessment Reference",
            "description":
                "Reference material for assessing cardiovascular risk factors during routine clinical care.",
            "topic": "Cardiology",
            "category": "Reference",
            "date": "Sep 7, 2026",
        },
        {
            "id": "resource-13",
            "title": "Heart Failure Patient Education",
            "description":
                "Educational material to support conversations with patients about heart failure symptoms, treatment, and monitoring.",
            "topic": "Heart Failure",
            "category": "Patient Resource",
            "date": "Sep 6, 2026",
        },
        {
            "id": "resource-14",
            "title": "Clinical Trial Eligibility Checklist",
            "description":
                "A quick reference for reviewing common eligibility considerations when identifying potential clinical trial candidates.",
            "topic": "Clinical Trials",
            "category": "Clinical Tool",
            "date": "Sep 5, 2026",
        },
        {
            "id": "resource-15",
            "title": "Managing Cardiovascular Risk in Diabetes",
            "description":
                "Clinical education covering cardiovascular risk considerations for patients with diabetes.",
            "topic": "Diabetes",
            "category": "Clinical Resource",
            "date": "Sep 4, 2026",
        },
        {
            "id": "resource-16",
            "title": "Medication Adherence Discussion Guide",
            "description":
                "A resource for discussing medication adherence, treatment barriers, and patient concerns.",
            "topic": "Patient Care",
            "category": "Patient Resource",
            "date": "Sep 3, 2026",
        },
        {
            "id": "resource-17",
            "title": "Hypertension Treatment Planning Tool",
            "description":
                "A clinical planning resource for evaluating treatment approaches and monitoring blood pressure control.",
            "topic": "Hypertension",
            "category": "Clinical Tool",
            "date": "Sep 2, 2026",
        },
        {
            "id": "resource-18",
            "title": "Cardiology Clinical Education Hub",
            "description":
                "A collection of educational materials covering cardiovascular conditions, treatment, and prevention.",
            "topic": "Cardiology",
            "category": "Educational Resource",
            "date": "Sep 1, 2026",
        },
        {
            "id": "resource-19",
            "title": "Care Coordination Best Practices",
            "description":
                "Resources focused on communication and coordination between primary care providers and specialists.",
            "topic": "Care Coordination",
            "category": "Practice Resource",
            "date": "Aug 30, 2026",
        },
        {
            "id": "resource-20",
            "title": "Patient Conversation Starter Guide",
            "description":
                "A collection of prompts and resources to support productive conversations between HCPs and patients.",
            "topic": "Patient Care",
            "category": "Patient Resource",
            "date": "Aug 28, 2026",
        },
    ]

    # --------------------------------------------------------
    # Add resources to AI search candidates
    # --------------------------------------------------------

    for resource in resources:

        search_text = (
            f"Title: {resource['title']}\n"
            f"Description: {resource['description']}\n"
            f"Topic: {resource['topic']}\n"
            f"Category: {resource['category']}"
        )

        candidates.append(
            {
                "id": resource["id"],

                "resultType": "resource",

                "title": resource["title"],

                "description":
                    resource["description"],

                "topic":
                    resource["topic"],

                "category":
                    resource["category"],

                "date":
                    resource["date"],

                "searchText":
                    search_text,
            }
        )

    # ========================================================
    # AI RANKING
    # ========================================================

    results = rank_search_results(
        query=query,
        candidates=candidates,
        result_type=(
            "healthcare SMS messages and "
            "healthcare resources"
        ),
        limit=request.limit,
    )

    # --------------------------------------------------------
    # Return results
    # --------------------------------------------------------

    return {
        "success": True,
        "query": query,
        "results": results,
        "count": len(results),
    }

# ============================================================
# SEARCH GLOBAL DISCUSSIONS
# ============================================================

@app.post("/discussions/search")
def search_discussions(
    request: SearchRequest,
    authorization: Optional[str] = Header(
        default=None
    ),
):
    """
    Search globally available discussions.

    Firestore:
        discussions/{discussionId}

    Unlike /messages/search, this endpoint does NOT restrict
    discussions to the current user.
    """

    # --------------------------------------------------------
    # Authenticate the user.
    #
    # Remove this block if you intentionally want discussions
    # to be publicly searchable without authentication.
    # --------------------------------------------------------

    get_current_user(
        authorization
    )

    query = request.query.strip()

    if not query:
        raise HTTPException(
            status_code=400,
            detail="Search query is required.",
        )

    # --------------------------------------------------------
    # Get all global discussions
    # --------------------------------------------------------

    discussion_documents = (
        db
        .collection("discussions")
        .stream()
    )

    candidates = []

    for document in discussion_documents:

        data = document.to_dict() or {}

        title = data.get(
            "title",
            "",
        )

        description = data.get(
            "description",
            "",
        )

        specialty = data.get(
            "specialty",
            "",
        )

        # ----------------------------------------------------
        # Search title + description + specialty.
        # ----------------------------------------------------

        search_text = (
            f"Title: {title}\n"
            f"Description: {description}\n"
            f"Specialty: {specialty}"
        )

        candidates.append(
            {
                "id":
                    document.id,

                "title":
                    title,

                "description":
                    description,

                "specialty":
                    specialty,

                "participantCount":
                    data.get(
                        "participantCount",
                        0,
                    ),

                "popular":
                    data.get(
                        "popular",
                        False,
                    ),

                "source":
                    data.get(
                        "source",
                        "",
                    ),

                "searchText":
                    search_text,
            }
        )

    # --------------------------------------------------------
    # Rank discussions
    # --------------------------------------------------------

    results = rank_search_results(
        query=query,
        candidates=candidates,
        result_type="global healthcare discussions",
        limit=request.limit,
    )

    return {
        "success": True,
        "query": query,
        "results": results,
        "count": len(results),
    }
