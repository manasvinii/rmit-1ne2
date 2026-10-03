-- Run ONCE, manually, in the Supabase SQL editor against the existing prototype tables.
-- Not auto-applied because it touches tables created outside this repository.

-- 1. Remove duplicate rows created by the old insert-only Canvas sync, then add the keys
--    that the new idempotent upsert relies on.
DELETE FROM "Courses" a USING "Courses" b
 WHERE a.ctid < b.ctid AND a.user_id = b.user_id AND a.course_id = b.course_id;
DELETE FROM "Assignments" a USING "Assignments" b
 WHERE a.ctid < b.ctid AND a.user_id = b.user_id AND a.assignment_id = b.assignment_id;

ALTER TABLE "Courses"     ADD CONSTRAINT courses_user_course_uniq UNIQUE (user_id, course_id);
ALTER TABLE "Assignments" ADD CONSTRAINT assignments_user_assignment_uniq UNIQUE (user_id, assignment_id);

-- 2. Assignment text is needed to link assessments to lecture concepts.
ALTER TABLE "Assignments" ADD COLUMN IF NOT EXISTS description TEXT;
ALTER TABLE "Assignments" ADD COLUMN IF NOT EXISTS html_url TEXT;

-- 3. Passwords are now bcrypt hashes and Canvas tokens are Fernet ciphertext. Existing plaintext
--    passwords are re-hashed automatically on the user's next successful login, and plaintext
--    tokens are re-encrypted on first use. To force it immediately, ask users to re-register.

-- 4. Block direct client access; only the backend (service role) should touch these tables.
ALTER TABLE "User"             ENABLE ROW LEVEL SECURITY;
ALTER TABLE "Courses"          ENABLE ROW LEVEL SECURITY;
ALTER TABLE "Assignments"      ENABLE ROW LEVEL SECURITY;
ALTER TABLE "Course_timetable" ENABLE ROW LEVEL SECURITY;
