"""
Campus Eye — DB Seed Script
Creates a few demo users with face embeddings for testing.
Run: python scripts/seed_db.py
"""
import asyncio
import sys
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).parent.parent))


async def seed():
    from app.database import init_db, AsyncSessionLocal
    from app.models import User, FaceEmbedding, Setting, SystemMode, UserRole
    import numpy as np

    print("▸ Initialising database...")
    await init_db()

    async with AsyncSessionLocal() as db:
        # ── Seed default mode setting ──────────────────────────────────────
        existing = await db.get(Setting, "system_mode")
        if not existing:
            db.add(Setting(key="system_mode", value="normal"))
            print("  ✔ Default mode set: normal")

        # ── Seed demo users with random embeddings ─────────────────────────
        demo_users = [
            {"name": "Alice Johnson",  "role": UserRole.invigilator, "student_id": "INV001"},
            {"name": "Bob Smith",      "role": UserRole.student,     "student_id": "STU001"},
            {"name": "Carol White",    "role": UserRole.student,     "student_id": "STU002"},
            {"name": "David Lee",      "role": UserRole.staff,       "student_id": "STF001"},
        ]

        for u in demo_users:
            user = User(
                name=u["name"],
                role=u["role"],
                student_id=u["student_id"],
            )
            db.add(user)
            await db.flush()

            # Random 512-dim L2-normalised embedding (for demo only)
            raw = np.random.randn(512).astype(np.float32)
            emb_vec = raw / (np.linalg.norm(raw) + 1e-6)

            db.add(FaceEmbedding(user_id=user.id, embedding=emb_vec.tolist()))
            print(f"  ✔ Seeded: {u['name']} ({u['role'].value})")

        await db.commit()

    print("\nSeed complete. Register real faces via the dashboard for accurate recognition.")


if __name__ == "__main__":
    asyncio.run(seed())
