-- HR Course Builder Showcase seed data for platform_backend.db.
-- This is a SQLite script. It is intentionally not executed by the app.
-- It removes only prior rows with the "HR Builder Showcase:" / "HR Seed Showcase:" names,
-- then recreates a rich set of courses, modules, linked tests, sections, and questions.

BEGIN TRANSACTION;

CREATE TEMP TABLE IF NOT EXISTS seed_refs (
    key TEXT PRIMARY KEY,
    id INTEGER NOT NULL
);

DELETE FROM seed_refs;

-- Seed display users for author/approver and access-preview data.
-- Password hashes are intentionally not valid login credentials.
INSERT OR IGNORE INTO users (
    username,
    email,
    password_hash,
    role,
    credits,
    is_active,
    created_at,
    created_by_id
) VALUES (
    'hr_seed_author',
    'hr-seed-author@example.com',
    'seed-not-for-login$seed-not-for-login',
    'moderator',
    0,
    1,
    CURRENT_TIMESTAMP,
    NULL
);

INSERT OR IGNORE INTO users (
    username,
    email,
    password_hash,
    role,
    credits,
    is_active,
    created_at,
    created_by_id
) VALUES (
    'hr_seed_learner',
    'hr-seed-learner@example.com',
    'seed-not-for-login$seed-not-for-login',
    'user',
    12,
    1,
    CURRENT_TIMESTAMP,
    (SELECT id FROM users WHERE username = 'hr_seed_author')
);

UPDATE users
SET role = 'moderator',
    is_active = 1
WHERE username = 'hr_seed_author';

UPDATE users
SET role = 'user',
    credits = 12,
    is_active = 1
WHERE username = 'hr_seed_learner';

INSERT OR REPLACE INTO seed_refs (key, id)
SELECT 'author', id FROM users WHERE username = 'hr_seed_author';

INSERT OR REPLACE INTO seed_refs (key, id)
SELECT 'learner', id FROM users WHERE username = 'hr_seed_learner';

-- Clean previous showcase content only.
DELETE FROM test_access_overrides
WHERE test_config_id IN (
    SELECT id FROM test_configs WHERE topic_name LIKE 'HR Seed Showcase:%'
);

DELETE FROM test_comments
WHERE test_config_id IN (
    SELECT id FROM test_configs WHERE topic_name LIKE 'HR Seed Showcase:%'
);

DELETE FROM attempts
WHERE test_config_id IN (
    SELECT id FROM test_configs WHERE topic_name LIKE 'HR Seed Showcase:%'
);

DELETE FROM questions
WHERE test_config_id IN (
    SELECT id FROM test_configs WHERE topic_name LIKE 'HR Seed Showcase:%'
);

DELETE FROM test_sections
WHERE test_config_id IN (
    SELECT id FROM test_configs WHERE topic_name LIKE 'HR Seed Showcase:%'
);

DELETE FROM test_configs
WHERE topic_name LIKE 'HR Seed Showcase:%';

DELETE FROM course_completions
WHERE course_id IN (
    SELECT id FROM courses WHERE title LIKE 'HR Builder Showcase:%'
);

DELETE FROM course_modules
WHERE course_id IN (
    SELECT id FROM courses WHERE title LIKE 'HR Builder Showcase:%'
);

DELETE FROM courses
WHERE title LIKE 'HR Builder Showcase:%';

-- Main approved course: exercises full preview, full curriculum, linked tests, and mixed resources.
INSERT INTO courses (
    title,
    summary,
    content,
    is_active,
    created_at,
    created_by_id,
    approval_status,
    approved_by_id,
    approved_at
) VALUES (
    'HR Builder Showcase: Employee Lifecycle Academy',
    'A premium HR learning path covering hiring, onboarding, policy decisions, employee relations, and compliance checkpoints.',
    '# Welcome to the HR Academy
Build confidence across the employee lifecycle with practical policy decisions, manager-ready scripts, and scenario-based checks.

## Outcomes
**Learners will be able to** evaluate onboarding readiness, spot employee-relations risk, document policy exceptions, and choose the right escalation path.

Use the lesson list, resources, video module, attached handbook, presentation deck, linked tests, published state, approval badges, and the live right-side preview to inspect the full course builder experience.',
    1,
    CURRENT_TIMESTAMP,
    (SELECT id FROM seed_refs WHERE key = 'author'),
    'approved',
    (SELECT id FROM seed_refs WHERE key = 'author'),
    CURRENT_TIMESTAMP
);

INSERT OR REPLACE INTO seed_refs (key, id)
SELECT 'course_main', id
FROM courses
WHERE title = 'HR Builder Showcase: Employee Lifecycle Academy';

INSERT INTO course_modules (
    course_id,
    title,
    module_type,
    content,
    resource_url,
    order_index,
    is_active
) VALUES (
    (SELECT id FROM seed_refs WHERE key = 'course_main'),
    'Welcome Brief: The Employee Lifecycle Map',
    'markdown',
    '# The lifecycle at a glance
HR work moves through **attract**, **hire**, **onboard**, **support**, **develop**, and **transition**.

## Builder checks
This markdown lesson intentionally uses headings, **bold text**, *emphasis*, inline `policy-code`, and a link: [SHRM](https://www.shrm.org).

## Learner takeaway
Every HR decision should leave a clear, respectful, and auditable trail.',
    '',
    1,
    1
);

INSERT INTO course_modules (
    course_id,
    title,
    module_type,
    content,
    resource_url,
    order_index,
    is_active
) VALUES (
    (SELECT id FROM seed_refs WHERE key = 'course_main'),
    'Video Lesson: Manager Intake Conversation',
    'video',
    '## Watch focus
Listen for the manager goal, the employee impact, and whether the request needs HR, Legal, or Payroll review.

**After watching:** capture the facts before recommending action.',
    'https://www.youtube.com/watch?v=ysz5S6PUM-U',
    2,
    1
);

INSERT INTO course_modules (
    course_id,
    title,
    module_type,
    content,
    resource_url,
    order_index,
    is_active
) VALUES (
    (SELECT id FROM seed_refs WHERE key = 'course_main'),
    'Policy Handbook Review',
    'document',
    '## Document exercise
Review the attached handbook placeholder and identify where a manager would find attendance, accommodation, and discipline guidance.

Use this module to test document/PDF resource handling and the Open File action.',
    '/uploads/course_modules/hr-policy-handbook-sample.pdf',
    3,
    1
);

INSERT INTO course_modules (
    course_id,
    title,
    module_type,
    content,
    resource_url,
    order_index,
    is_active
) VALUES (
    (SELECT id FROM seed_refs WHERE key = 'course_main'),
    'Onboarding Deck: First 30 Days',
    'presentation',
    '## Slide deck activity
Use the deck placeholder to test the presentation path. The learner should understand role clarity, equipment readiness, benefits enrollment, and first-week manager check-ins.',
    '/uploads/course_modules/hr-onboarding-deck-sample.pptx',
    4,
    1
);

INSERT INTO course_modules (
    course_id,
    title,
    module_type,
    content,
    resource_url,
    order_index,
    is_active
) VALUES (
    (SELECT id FROM seed_refs WHERE key = 'course_main'),
    'Hidden Draft: Executive Escalation Playbook',
    'markdown',
    '# Draft lesson
This inactive lesson should appear as hidden in the builder list but should not count as a visible learner lesson.

Use it to inspect hidden-module styling and preview behavior.',
    '',
    5,
    0
);

-- Draft course: tests inactive/draft status and pending approval state.
INSERT INTO courses (
    title,
    summary,
    content,
    is_active,
    created_at,
    created_by_id,
    approval_status,
    approved_by_id,
    approved_at
) VALUES (
    'HR Builder Showcase: Compensation Draft Lab',
    'A draft compensation course used to test inactive courses, pending approval badges, sparse curriculum, and catalog search.',
    '# Draft compensation lab
This course is intentionally hidden from learners and pending approval. It helps verify that the course catalog and editor communicate state clearly.',
    0,
    CURRENT_TIMESTAMP,
    (SELECT id FROM seed_refs WHERE key = 'author'),
    'pending',
    NULL,
    NULL
);

INSERT OR REPLACE INTO seed_refs (key, id)
SELECT 'course_draft', id
FROM courses
WHERE title = 'HR Builder Showcase: Compensation Draft Lab';

INSERT INTO course_modules (
    course_id,
    title,
    module_type,
    content,
    resource_url,
    order_index,
    is_active
) VALUES (
    (SELECT id FROM seed_refs WHERE key = 'course_draft'),
    'Draft Pay Equity Checklist',
    'markdown',
    '# Pay equity review
Confirm job architecture, compensation range, approval authority, and documentation before a pay action is communicated.',
    '',
    1,
    1
);

-- Rejected course: tests rejected approval badge without cluttering the main scenario.
INSERT INTO courses (
    title,
    summary,
    content,
    is_active,
    created_at,
    created_by_id,
    approval_status,
    approved_by_id,
    approved_at
) VALUES (
    'HR Builder Showcase: Archived Policy Review',
    'A rejected sample course for approval-state and list-card testing.',
    '# Archived policy review
This content is seeded as rejected so the Courses catalog shows all review states.',
    1,
    CURRENT_TIMESTAMP,
    (SELECT id FROM seed_refs WHERE key = 'author'),
    'rejected',
    (SELECT id FROM seed_refs WHERE key = 'author'),
    CURRENT_TIMESTAMP
);

-- Linked test 1: foundation test with normal and multi-answer sections.
INSERT INTO test_configs (
    topic_name,
    level_name,
    duration_seconds,
    passing_percent,
    is_active,
    course_id,
    created_by_id,
    approval_status,
    approved_by_id,
    approved_at
) VALUES (
    'HR Seed Showcase: Employee Lifecycle Academy',
    'HR Foundations Check',
    1500,
    80.0,
    1,
    (SELECT id FROM seed_refs WHERE key = 'course_main'),
    (SELECT id FROM seed_refs WHERE key = 'author'),
    'approved',
    (SELECT id FROM seed_refs WHERE key = 'author'),
    CURRENT_TIMESTAMP
);

INSERT OR REPLACE INTO seed_refs (key, id)
SELECT 'test_foundations', id
FROM test_configs
WHERE topic_name = 'HR Seed Showcase: Employee Lifecycle Academy'
  AND level_name = 'HR Foundations Check';

INSERT INTO test_sections (
    test_config_id,
    name,
    select_count,
    points_per_question,
    order_index,
    requires_full_score,
    section_type,
    global_question
) VALUES (
    (SELECT id FROM seed_refs WHERE key = 'test_foundations'),
    'Policy Essentials',
    2,
    1,
    1,
    0,
    'regular',
    NULL
);

INSERT INTO test_sections (
    test_config_id,
    name,
    select_count,
    points_per_question,
    order_index,
    requires_full_score,
    section_type,
    global_question
) VALUES (
    (SELECT id FROM seed_refs WHERE key = 'test_foundations'),
    'Multi-Answer Compliance',
    1,
    2,
    2,
    0,
    'regular',
    NULL
);

INSERT OR REPLACE INTO seed_refs (key, id)
SELECT 'section_policy', id
FROM test_sections
WHERE test_config_id = (SELECT id FROM seed_refs WHERE key = 'test_foundations')
  AND name = 'Policy Essentials';

INSERT OR REPLACE INTO seed_refs (key, id)
SELECT 'section_multi', id
FROM test_sections
WHERE test_config_id = (SELECT id FROM seed_refs WHERE key = 'test_foundations')
  AND name = 'Multi-Answer Compliance';

INSERT INTO questions (
    test_config_id,
    section_id,
    question_text,
    options_json,
    correct_index
) VALUES (
    (SELECT id FROM seed_refs WHERE key = 'test_foundations'),
    (SELECT id FROM seed_refs WHERE key = 'section_policy'),
    'A manager wants to skip onboarding because the employee has prior experience. What should HR recommend?',
    '{"options":["Skip only benefits enrollment","Keep core onboarding and tailor role-specific depth","Wait until the employee asks for help","Replace onboarding with a final exam"],"correct_indices":[1]}',
    1
);

INSERT INTO questions (
    test_config_id,
    section_id,
    question_text,
    options_json,
    correct_index
) VALUES (
    (SELECT id FROM seed_refs WHERE key = 'test_foundations'),
    (SELECT id FROM seed_refs WHERE key = 'section_policy'),
    'Which record best supports a defensible employee-relations decision?',
    '{"options":["A private chat summary with no dates","A clear timeline, policy reference, participants, and action taken","A manager opinion stated as fact","A screenshot with no context"],"correct_indices":[1]}',
    1
);

INSERT INTO questions (
    test_config_id,
    section_id,
    question_text,
    options_json,
    correct_index
) VALUES (
    (SELECT id FROM seed_refs WHERE key = 'test_foundations'),
    (SELECT id FROM seed_refs WHERE key = 'section_policy'),
    'When should HR escalate a workplace concern to Legal or senior leadership?',
    '{"options":["Only after termination","When there is protected activity, safety risk, litigation threat, or executive involvement","Whenever the manager is frustrated","Never, HR should resolve every issue alone"],"correct_indices":[1]}',
    1
);

INSERT INTO questions (
    test_config_id,
    section_id,
    question_text,
    options_json,
    correct_index
) VALUES (
    (SELECT id FROM seed_refs WHERE key = 'test_foundations'),
    (SELECT id FROM seed_refs WHERE key = 'section_multi'),
    'Select all items that belong in a strong HR case note.',
    '{"options":["Objective facts","Dates and participants","Policy references","Speculation about motive","Next action owner"],"correct_indices":[0,1,2,4]}',
    0
);

-- Linked test 2: case scenario section with full-score requirement.
INSERT INTO test_configs (
    topic_name,
    level_name,
    duration_seconds,
    passing_percent,
    is_active,
    course_id,
    created_by_id,
    approval_status,
    approved_by_id,
    approved_at
) VALUES (
    'HR Seed Showcase: Employee Lifecycle Academy',
    'Employee Relations Case Simulation',
    2100,
    75.0,
    1,
    (SELECT id FROM seed_refs WHERE key = 'course_main'),
    (SELECT id FROM seed_refs WHERE key = 'author'),
    'approved',
    (SELECT id FROM seed_refs WHERE key = 'author'),
    CURRENT_TIMESTAMP
);

INSERT OR REPLACE INTO seed_refs (key, id)
SELECT 'test_case', id
FROM test_configs
WHERE topic_name = 'HR Seed Showcase: Employee Lifecycle Academy'
  AND level_name = 'Employee Relations Case Simulation';

INSERT INTO test_sections (
    test_config_id,
    name,
    select_count,
    points_per_question,
    order_index,
    requires_full_score,
    section_type,
    global_question
) VALUES (
    (SELECT id FROM seed_refs WHERE key = 'test_case'),
    'Case Scenario: Attendance Accommodation',
    2,
    3,
    1,
    1,
    'case_scenario',
    'Scenario: Jordan, a customer-support employee, has a sudden increase in attendance issues after sharing that a medical condition may require intermittent appointments. The manager wants to issue a final warning today because the team is short-staffed. HR has one prior attendance warning on file, no accommodation paperwork, and no recent performance issues.'
);

INSERT INTO test_sections (
    test_config_id,
    name,
    select_count,
    points_per_question,
    order_index,
    requires_full_score,
    section_type,
    global_question
) VALUES (
    (SELECT id FROM seed_refs WHERE key = 'test_case'),
    'Risk Triage',
    1,
    2,
    2,
    0,
    'regular',
    NULL
);

INSERT OR REPLACE INTO seed_refs (key, id)
SELECT 'section_case', id
FROM test_sections
WHERE test_config_id = (SELECT id FROM seed_refs WHERE key = 'test_case')
  AND name = 'Case Scenario: Attendance Accommodation';

INSERT OR REPLACE INTO seed_refs (key, id)
SELECT 'section_triage', id
FROM test_sections
WHERE test_config_id = (SELECT id FROM seed_refs WHERE key = 'test_case')
  AND name = 'Risk Triage';

INSERT INTO questions (
    test_config_id,
    section_id,
    question_text,
    options_json,
    correct_index
) VALUES (
    (SELECT id FROM seed_refs WHERE key = 'test_case'),
    (SELECT id FROM seed_refs WHERE key = 'section_case'),
    'What is the strongest first HR action in this scenario?',
    '{"options":["Approve the final warning immediately","Pause discipline long enough to gather facts and start the accommodation-interactive process","Tell the employee to use vacation time","Ignore the manager until paperwork arrives"],"correct_indices":[1]}',
    1
);

INSERT INTO questions (
    test_config_id,
    section_id,
    question_text,
    options_json,
    correct_index
) VALUES (
    (SELECT id FROM seed_refs WHERE key = 'test_case'),
    (SELECT id FROM seed_refs WHERE key = 'section_case'),
    'Which facts are most important before deciding whether discipline is appropriate?',
    '{"options":["Attendance dates and policy language","Whether Jordan is popular on the team","Accommodation request details and medical-certification process status","Manager staffing pressure","Prior similar cases and consistency"],"correct_indices":[0,2,4]}',
    0
);

INSERT INTO questions (
    test_config_id,
    section_id,
    question_text,
    options_json,
    correct_index
) VALUES (
    (SELECT id FROM seed_refs WHERE key = 'test_case'),
    (SELECT id FROM seed_refs WHERE key = 'section_case'),
    'What should HR tell the manager about timing?',
    '{"options":["Business need always overrides accommodation review","HR will review urgency, policy, and legal risk before a final warning is issued","Wait six months before any action","Terminate now and document later"],"correct_indices":[1]}',
    1
);

INSERT INTO questions (
    test_config_id,
    section_id,
    question_text,
    options_json,
    correct_index
) VALUES (
    (SELECT id FROM seed_refs WHERE key = 'test_case'),
    (SELECT id FROM seed_refs WHERE key = 'section_triage'),
    'Which issue category is the primary risk signal?',
    '{"options":["Payroll processing","Potential accommodation / protected leave issue","Dress code preference","Routine onboarding"],"correct_indices":[1]}',
    1
);

-- Draft-course linked test: shows pending approval and inactive course linkage.
INSERT INTO test_configs (
    topic_name,
    level_name,
    duration_seconds,
    passing_percent,
    is_active,
    course_id,
    created_by_id,
    approval_status,
    approved_by_id,
    approved_at
) VALUES (
    'HR Seed Showcase: Compensation Draft Lab',
    'Pay Equity Draft Gate',
    1200,
    70.0,
    0,
    (SELECT id FROM seed_refs WHERE key = 'course_draft'),
    (SELECT id FROM seed_refs WHERE key = 'author'),
    'pending',
    NULL,
    NULL
);

INSERT OR REPLACE INTO seed_refs (key, id)
SELECT 'test_draft', id
FROM test_configs
WHERE topic_name = 'HR Seed Showcase: Compensation Draft Lab'
  AND level_name = 'Pay Equity Draft Gate';

INSERT INTO test_sections (
    test_config_id,
    name,
    select_count,
    points_per_question,
    order_index,
    requires_full_score,
    section_type,
    global_question
) VALUES (
    (SELECT id FROM seed_refs WHERE key = 'test_draft'),
    'Draft Review',
    1,
    1,
    1,
    0,
    'regular',
    NULL
);

INSERT OR REPLACE INTO seed_refs (key, id)
SELECT 'section_draft', id
FROM test_sections
WHERE test_config_id = (SELECT id FROM seed_refs WHERE key = 'test_draft')
  AND name = 'Draft Review';

INSERT INTO questions (
    test_config_id,
    section_id,
    question_text,
    options_json,
    correct_index
) VALUES (
    (SELECT id FROM seed_refs WHERE key = 'test_draft'),
    (SELECT id FROM seed_refs WHERE key = 'section_draft'),
    'What should be verified before approving a compensation exception?',
    '{"options":["Only the manager request","Budget, job level, internal equity, approval authority, and documentation","Employee preference only","Nothing if the employee is high-performing"],"correct_indices":[1]}',
    1
);

-- Sample override lets the access table contain visible data for the seeded learner/test.
INSERT OR IGNORE INTO test_access_overrides (
    user_id,
    test_config_id,
    granted_at
) VALUES (
    (SELECT id FROM seed_refs WHERE key = 'learner'),
    (SELECT id FROM seed_refs WHERE key = 'test_case'),
    CURRENT_TIMESTAMP
);

DROP TABLE seed_refs;

COMMIT;
