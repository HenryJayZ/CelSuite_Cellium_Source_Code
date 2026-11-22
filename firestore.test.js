const {
  initializeTestEnvironment,
  assertFails,
  assertSucceeds,
} = require("@firebase/rules-unit-testing");
const { test, before, after, beforeEach } = require("node:test");
const fs = require("node:fs");

let testEnv;
const PROJECT_ID = process.env.GCP_PROJECT || "demo-no-project";
const ALICE_UID = "alice_uid_123";
const BOB_UID = "bob_uid_456";

const [emulatorHost, emulatorPortStr] = (
  process.env.FIRESTORE_EMULATOR_HOST || "127.0.0.1:8085"
).split(":");
const emulatorPort = parseInt(emulatorPortStr, 10);

function pastDate(offsetMs = 5000) {
  return new Date(Date.now() - offsetMs);
}

before(async () => {
  const rules = fs.readFileSync("./firestore.rules", "utf8");
  testEnv = await initializeTestEnvironment({
    projectId: PROJECT_ID,
    firestore: {
      rules,
      host: emulatorHost,
      port: emulatorPort,
    },
  });
});

after(async () => {
  if (testEnv) {
    await testEnv.cleanup();
  }
});

beforeEach(async () => {
  if (testEnv) {
    await testEnv.clearFirestore();
  }
});

test("Unauthenticated user cannot read or write any collection", async () => {
  const db = testEnv.unauthenticatedContext().firestore();
  await assertFails(db.collection("users").doc(ALICE_UID).collection("sessions").get());
  await assertFails(
    db.collection("users").doc(ALICE_UID).collection("sessions").doc("sess_1").set({
      userId: ALICE_UID,
      title: "Unauthorized",
      personaId: "default",
      modelName: "gemini-3.8-flash",
      pinned: false,
      messageCount: 0,
      tokenCount: 0,
      lastMessagePreview: "",
      createdAt: pastDate(),
      updatedAt: pastDate(),
    })
  );
  await assertFails(db.collection("users").doc(ALICE_UID).collection("personas").get());
  await assertFails(db.collection("users").doc(ALICE_UID).collection("memories").get());
});

test("Owner can create, list, update, and delete sessions; cross-user & shadow fields blocked", async () => {
  const aliceDb = testEnv.authenticatedContext(ALICE_UID).firestore();
  const bobDb = testEnv.authenticatedContext(BOB_UID).firestore();
  const created = pastDate(10000);

  const sessionRef = aliceDb.collection("users").doc(ALICE_UID).collection("sessions").doc("sess_1");

  // Valid create matching Kotlin CelliumRepository.createSession
  await assertSucceeds(
    sessionRef.set({
      userId: ALICE_UID,
      title: "New Chat",
      personaId: "default",
      modelName: "gemini-3.8-flash",
      pinned: false,
      messageCount: 0,
      tokenCount: 0,
      lastMessagePreview: "",
      createdAt: created,
      updatedAt: created,
    })
  );

  // List own sessions succeeds
  await assertSucceeds(
    aliceDb.collection("users").doc(ALICE_UID).collection("sessions").orderBy("updatedAt", "desc").get()
  );

  // Partial update: pin toggle
  await assertSucceeds(
    sessionRef.update({
      pinned: true,
      updatedAt: pastDate(1000),
    })
  );

  // Partial update: message metrics & title
  await assertSucceeds(
    sessionRef.update({
      title: "Kotlin Port Planning",
      messageCount: 2,
      tokenCount: 420,
      lastMessagePreview: "Let's build Cellium!",
      updatedAt: pastDate(500),
    })
  );

  // Reject shadow field (ghost key)
  await assertFails(
    aliceDb.collection("users").doc(ALICE_UID).collection("sessions").doc("sess_ghost").set({
      id: "sess_ghost",
      userId: ALICE_UID,
      title: "Ghost",
      personaId: "default",
      modelName: "gemini-3.8-flash",
      pinned: false,
      messageCount: 0,
      tokenCount: 0,
      lastMessagePreview: "",
      createdAt: created,
      updatedAt: created,
    })
  );

  // Reject future timestamp
  await assertFails(
    aliceDb.collection("users").doc(ALICE_UID).collection("sessions").doc("sess_future").set({
      userId: ALICE_UID,
      title: "Future",
      personaId: "default",
      modelName: "gemini-3.8-flash",
      pinned: false,
      messageCount: 0,
      tokenCount: 0,
      lastMessagePreview: "",
      createdAt: new Date(Date.now() + 60000),
      updatedAt: new Date(Date.now() + 60000),
    })
  );

  // Reject mutating immutable createdAt
  await assertFails(
    sessionRef.update({
      createdAt: pastDate(200),
      updatedAt: pastDate(200),
    })
  );

  // Cross-user isolation: Bob cannot read, update, or delete Alice's session
  const bobRef = bobDb.collection("users").doc(ALICE_UID).collection("sessions").doc("sess_1");
  await assertFails(bobRef.get());
  await assertFails(bobDb.collection("users").doc(ALICE_UID).collection("sessions").get());
  await assertFails(bobRef.update({ pinned: false, updatedAt: pastDate(200) }));
  await assertFails(bobRef.delete());

  // Owner delete succeeds
  await assertSucceeds(sessionRef.delete());
});

test("Messages subcollection enforces ownership, role enum, and immutability", async () => {
  const aliceDb = testEnv.authenticatedContext(ALICE_UID).firestore();
  const bobDb = testEnv.authenticatedContext(BOB_UID).firestore();
  const created = pastDate(8000);

  const msgRef = aliceDb
    .collection("users")
    .doc(ALICE_UID)
    .collection("sessions")
    .doc("sess_1")
    .collection("messages")
    .doc("msg_1");

  await assertSucceeds(
    msgRef.set({
      userId: ALICE_UID,
      sessionId: "sess_1",
      role: "assistant",
      content: "Hey! Ready to build Cellium on Android?",
      thought: "Planning architecture",
      mood: "excited",
      modelName: "gemini-3.8-flash",
      tokenEstimate: 32,
      latencyMs: 640,
      hasAttachment: false,
      createdAt: created,
    })
  );

  // List messages ordered by createdAt
  await assertSucceeds(
    aliceDb
      .collection("users")
      .doc(ALICE_UID)
      .collection("sessions")
      .doc("sess_1")
      .collection("messages")
      .orderBy("createdAt", "asc")
      .get()
  );

  // Reject invalid role
  await assertFails(
    aliceDb
      .collection("users")
      .doc(ALICE_UID)
      .collection("sessions")
      .doc("sess_1")
      .collection("messages")
      .doc("msg_bad_role")
      .set({
        userId: ALICE_UID,
        sessionId: "sess_1",
        role: "system_admin",
        content: "spoof",
        thought: "",
        mood: "idle",
        modelName: "gemini-3.8-flash",
        tokenEstimate: 1,
        latencyMs: 10,
        hasAttachment: false,
        createdAt: created,
      })
  );

  // Cross-user access denied
  await assertFails(
    bobDb
      .collection("users")
      .doc(ALICE_UID)
      .collection("sessions")
      .doc("sess_1")
      .collection("messages")
      .get()
  );
});

test("Personas and memories enforce schema and owner isolation", async () => {
  const aliceDb = testEnv.authenticatedContext(ALICE_UID).firestore();
  const bobDb = testEnv.authenticatedContext(BOB_UID).firestore();
  const ts = pastDate(5000);

  // Custom persona CRUD
  const personaRef = aliceDb.collection("users").doc(ALICE_UID).collection("personas").doc("p_1");
  await assertSucceeds(
    personaRef.set({
      userId: ALICE_UID,
      name: "Cel Hacker",
      emoji: "⚡",
      tagline: "Fast Kotlin debugger",
      systemPrompt: "You are Cel in Kotlin engineering mode.",
      accentHex: "#A855F7",
      createdAt: ts,
      updatedAt: ts,
    })
  );
  await assertSucceeds(aliceDb.collection("users").doc(ALICE_UID).collection("personas").get());
  await assertFails(bobDb.collection("users").doc(ALICE_UID).collection("personas").get());

  // Memory preset CRUD + toggle
  const memRef = aliceDb.collection("users").doc(ALICE_UID).collection("memories").doc("m_1");
  await assertSucceeds(
    memRef.set({
      userId: ALICE_UID,
      title: "Preferred Stack",
      content: "User prefers Kotlin, Jetpack Compose, and Material 3.",
      enabled: true,
      createdAt: ts,
      updatedAt: ts,
    })
  );
  await assertSucceeds(memRef.update({ enabled: false, updatedAt: pastDate(1000) }));
  await assertFails(bobDb.collection("users").doc(ALICE_UID).collection("memories").doc("m_1").delete());
});
