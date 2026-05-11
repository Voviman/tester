const { createApp } = Vue;

createApp({
    data() {
        return {
            booting: true,
            busy: false,
            authenticated: false,
            me: null,
            view: "dashboard",
            error: "",
            success: "",
            login: {
                username: "",
                password: "",
            },
            userSearchQuery: "",
            testSearchQuery: "",
            testFilterTopic: "",
            testFilterLevel: "",
            testFilterDuration: "",
            commentDrafts: {},
            commentVisibleCounts: {},
            commentSectionExpanded: {},
            preloadTtlMs: 45_000,
            preloadStatus: {
                dashboard: false,
                profile: false,
                admin: false,
            },
            preloadBusy: {
                dashboard: false,
                profile: false,
                admin: false,
            },
            preloadFetchedAt: {
                dashboard: 0,
                profile: 0,
                admin: 0,
            },
            dashboard: {
                profile: {
                    user: { credits: 0 },
                    tests_done: 0,
                    success_rate_percent: 0,
                },
                social_dashboard: {
                    tests: [],
                    active_users: [],
                    recent_results: [],
                    following_user_ids: [],
                },
                comments_by_test: {},
            },
            profile: {
                profile: {
                    user: { username: "", email: "", credits: 0 },
                    tests_done: 0,
                    passed_tests: 0,
                    failed_tests: 0,
                    success_rate_percent: 0,
                },
                my_results: [],
            },
            profileIsPublic: false,
            profilePublicRole: "",
            profileTargetUserId: 0,
            profileLoading: false,
            desktopParticipationToken: "",
            testSession: null,
            admin: {
                users: [],
                test_configs: [],
                sections: [],
                questions: [],
                activeTab: "tests",
                testSearchQuery: "",
                userSearchQuery: "",
                selectedTestConfigId: 0,
                selectedUserId: 0,
                selectedUserStats: null,
                selectedUserStatsFetchedAt: 0,
                createUser: {
                    username: "",
                    email: "",
                    password: "",
                    role: "user",
                    credits: 0,
                },
                editUser: {
                    username: "",
                    email: "",
                    role: "user",
                    credits: 0,
                    is_active: true,
                    password: "",
                    credits_to_add: 1,
                },
                testFormMode: "create",
                userFormMode: "create",
                userModalOpen: false,
                testModalOpen: false,
                testForm: {
                    id: 0,
                    topic_name: "",
                    level_name: "",
                    duration_minutes: 15,
                    passing_percent: 60,
                    is_active: true,
                },
                questionModalOpen: false,
                questionModalMode: "create",
                questionForm: {
                    id: 0,
                    test_config_id: 0,
                    section_id: null,
                    question_text: "",
                    options: ["", "", "", ""],
                    correct_indices: [],
                },
                sectionForm: {
                    id: 0,
                    test_config_id: 0,
                    name: "",
                    select_count: 1,
                    points_per_question: 1,
                    requires_full_score: false,
                    section_type: "regular",
                    global_question: "",
                },
                draggingSectionId: 0,
                confirmModalOpen: false,
                confirmModal: {
                    title: "",
                    message: "",
                    action: "",
                },
            },
        };
    },
    computed: {
        isAdmin() {
            return this.me && (this.me.role === "admin" || this.me.role === "super_admin");
        },
        filteredActiveUsers() {
            const users = this.dashboard?.social_dashboard?.active_users || [];
            const query = this.userSearchQuery.trim().toLowerCase();
            const list = query
                ? users.filter((u) => String(u.username || "").toLowerCase().includes(query))
                : users.slice();

            const adminRank = (role) => {
                const r = String(role ?? "").toLowerCase();
                if (r === "super_admin") return 0;
                if (r === "admin") return 1;
                return 2;
            };
            list.sort((a, b) => {
                const ra = adminRank(a.role);
                const rb = adminRank(b.role);
                if (ra !== rb) return ra - rb;
                const testsA = Number(a.tests_done ?? 0);
                const testsB = Number(b.tests_done ?? 0);
                if (testsB !== testsA) return testsB - testsA;
                return String(a.username || "").localeCompare(String(b.username || ""), undefined, {
                    sensitivity: "base",
                });
            });
            return list;
        },
        dashboardTestsRaw() {
            return this.dashboard?.social_dashboard?.tests || [];
        },
        testsFilteredByTopicOnly() {
            const tests = this.dashboardTestsRaw;
            const topic = String(this.testFilterTopic || "");
            if (!topic) return tests;
            return tests.filter((t) => t.topic_name === topic);
        },
        testsFilteredByTopicAndLevel() {
            let tests = this.testsFilteredByTopicOnly;
            const level = String(this.testFilterLevel || "");
            if (level) tests = tests.filter((t) => t.level_name === level);
            return tests;
        },
        testFilterTopicOptions() {
            const seen = new Set();
            for (const t of this.dashboardTestsRaw) {
                const name = t.topic_name;
                if (name) seen.add(name);
            }
            return [...seen].sort((a, b) => a.localeCompare(b, undefined, { sensitivity: "base" }));
        },
        testFilterLevelOptions() {
            const seen = new Set();
            for (const t of this.testsFilteredByTopicOnly) {
                const name = t.level_name;
                if (name) seen.add(name);
            }
            return [...seen].sort((a, b) => a.localeCompare(b, undefined, { sensitivity: "base" }));
        },
        testFilterDurationOptions() {
            const seen = new Set();
            for (const t of this.testsFilteredByTopicAndLevel) {
                const mins = Math.max(0, Math.floor(Number(t.duration_seconds || 0) / 60));
                seen.add(mins);
            }
            return [...seen].sort((a, b) => a - b);
        },
        filteredDashboardTests() {
            let tests = this.dashboardTestsRaw;
            if (this.testFilterTopic) {
                tests = tests.filter((t) => t.topic_name === this.testFilterTopic);
            }
            if (this.testFilterLevel) {
                tests = tests.filter((t) => t.level_name === this.testFilterLevel);
            }
            if (this.testFilterDuration !== "") {
                const want = Number(this.testFilterDuration);
                if (Number.isFinite(want)) {
                    tests = tests.filter(
                        (t) => Math.floor(Number(t.duration_seconds || 0) / 60) === want,
                    );
                }
            }
            const query = String(this.testSearchQuery || "").trim().toLowerCase();
            if (query) {
                tests = tests.filter((t) => {
                    const topic = String(t.topic_name || "").toLowerCase();
                    const level = String(t.level_name || "").toLowerCase();
                    const combined = `${topic} - ${level}`;
                    return topic.includes(query) || level.includes(query) || combined.includes(query);
                });
            }
            return tests;
        },
        snapshotSidebarUsername() {
            const fromMe = String(this.me?.username || "").trim();
            if (fromMe) return fromMe;
            const fromProfile = String(this.dashboard?.profile?.user?.username || "").trim();
            return fromProfile || "You";
        },
        snapshotSidebarIsAdmin() {
            return (
                this.isAdminRole(this.me?.role) ||
                this.isAdminRole(this.dashboard?.profile?.user?.role)
            );
        },
        adminTestSubmitLabel() {
            return this.admin.testFormMode === "update" ? "Update Test" : "Create Test";
        },
        adminTestModalTitle() {
            return this.admin.testFormMode === "update" ? "Update Test" : "Create Test";
        },
        filteredAdminTestConfigs() {
            const items = this.admin.test_configs || [];
            const query = String(this.admin.testSearchQuery || "").trim().toLowerCase();
            if (!query) return items;
            return items.filter((item) => {
                const topic = String(item.topic_name || "").toLowerCase();
                const level = String(item.level_name || "").toLowerCase();
                return topic.includes(query) || level.includes(query);
            });
        },
        filteredAdminUsers() {
            const users = this.admin.users || [];
            const query = String(this.admin.userSearchQuery || "").trim().toLowerCase();
            if (!query) return users;
            return users.filter((user) => {
                const username = String(user.username || "").toLowerCase();
                const email = String(user.email || "").toLowerCase();
                return username.includes(query) || email.includes(query);
            });
        },
        activeAdminTestConfig() {
            if (!this.admin.test_configs.length) return null;
            const selectedId = Number(this.admin.selectedTestConfigId);
            return this.admin.test_configs.find((item) => item.id === selectedId) || this.admin.test_configs[0];
        },
        activeAdminUser() {
            if (!this.admin.users.length) return null;
            const selectedId = Number(this.admin.selectedUserId);
            return this.admin.users.find((item) => item.id === selectedId) || this.admin.users[0];
        },
        activeAdminTestQuestions() {
            const target = this.activeAdminTestConfig;
            if (!target) return [];
            const targetId = Number(target.id);
            return (this.admin.questions || []).filter((item) => Number(item.test_config_id) === targetId);
        },
        activeAdminTestSections() {
            const target = this.activeAdminTestConfig;
            if (!target) return [];
            const targetId = Number(target.id);
            return (this.admin.sections || [])
                .filter((item) => Number(item.test_config_id) === targetId)
                .slice()
                .sort((a, b) => {
                    const orderA = Number(a.order_index || 0);
                    const orderB = Number(b.order_index || 0);
                    if (orderA !== orderB) return orderA - orderB;
                    return Number(a.id || 0) - Number(b.id || 0);
                });
        },
        activeAdminQuestionGroups() {
            const questions = this.activeAdminTestQuestions;
            const groups = this.activeAdminTestSections.map((section) => ({
                id: Number(section.id),
                name: section.name,
                section,
                questions: questions.filter((question) => Number(question.section_id || 0) === Number(section.id)),
            }));
            const unsectioned = questions.filter((question) => !Number(question.section_id || 0));
            if (unsectioned.length) {
                groups.push({
                    id: 0,
                    name: "Unsectioned",
                    section: null,
                    questions: unsectioned,
                });
            }
            return groups;
        },
        activeAdminSelectedQuestionCount() {
            return this.activeAdminTestSections.reduce((total, section) => {
                return total + Math.min(Number(section.select_count || 0), Number(section.question_count || 0));
            }, 0);
        },
        activeAdminMaxScore() {
            return this.activeAdminTestSections.reduce((total, section) => {
                const selected = Math.min(Number(section.select_count || 0), Number(section.question_count || 0));
                return total + selected * Number(section.points_per_question || 1);
            }, 0);
        },
        adminQuestionOptionIndexes() {
            const questions = this.activeAdminTestQuestions;
            if (!questions.length) return [0, 1, 2];
            let maxOptions = 0;
            for (const question of questions) {
                maxOptions = Math.max(maxOptions, Array.isArray(question.options) ? question.options.length : 0);
            }
            const safeCount = Math.min(Math.max(maxOptions, 3), 6);
            return Array.from({ length: safeCount }, (_item, index) => index);
        },
        questionModalTitle() {
            return this.admin.questionModalMode === "edit" ? "Change Question" : "Add Question";
        },
        questionSubmitLabel() {
            return this.admin.questionModalMode === "edit" ? "Update Question" : "Create Question";
        },
        profileOutcomeTotal() {
            const p = Number(this.profile?.profile?.passed_tests ?? 0);
            const f = Number(this.profile?.profile?.failed_tests ?? 0);
            return p + f;
        },
        profileOutcomeDonutStyle() {
            const pr = this.profile?.profile;
            const p = Number(pr?.passed_tests ?? 0);
            const f = Number(pr?.failed_tests ?? 0);
            const t = p + f;
            if (t <= 0) {
                return { background: "conic-gradient(#e2e8f0 0deg 360deg)" };
            }
            const deg = (p / t) * 360;
            const ok = "#16a34a";
            const rest = "#94a3b8";
            return {
                background: `conic-gradient(${ok} 0deg, ${ok} ${deg}deg, ${rest} ${deg}deg, ${rest} 360deg)`,
            };
        },
        profileSuccessGaugeStyle() {
            const pct = Math.max(
                0,
                Math.min(100, Number(this.profile?.profile?.success_rate_percent ?? 0)),
            );
            const deg = (pct / 100) * 360;
            const fill = "#2563eb";
            const track = "#e2e8f0";
            return {
                background: `conic-gradient(${fill} 0deg, ${fill} ${deg}deg, ${track} ${deg}deg, ${track} 360deg)`,
            };
        },
        profileStackPassPercent() {
            const p = Number(this.profile?.profile?.passed_tests ?? 0);
            const f = Number(this.profile?.profile?.failed_tests ?? 0);
            const t = p + f;
            if (t <= 0) return 0;
            return (p / t) * 100;
        },
        profileStackFailPercent() {
            const p = Number(this.profile?.profile?.passed_tests ?? 0);
            const f = Number(this.profile?.profile?.failed_tests ?? 0);
            const t = p + f;
            if (t <= 0) return 0;
            return (f / t) * 100;
        },
        profileShowsAdminBadge() {
            if (this.profileIsPublic) {
                return this.isAdminRole(this.normalizeRole(this.profilePublicRole));
            }
            return (
                this.isAdminRole(this.normalizeRole(this.profile?.profile?.user?.role)) ||
                this.isAdminRole(this.normalizeRole(this.me?.role))
            );
        },
        profileActivityBarPercent() {
            const n = Number(this.profile?.profile?.tests_done ?? 0);
            if (n <= 0) return 0;
            const fullAt = 25;
            return Math.min(100, Math.round((n / fullAt) * 100));
        },
        profileAvgRecentPercent() {
            const rows = this.profile?.my_results || [];
            if (!Array.isArray(rows) || rows.length === 0) return null;
            const sum = rows.reduce((s, r) => s + Number(r.success_percent ?? 0), 0);
            const v = sum / rows.length;
            return Number.isFinite(v) ? v.toFixed(1) : null;
        },
        testParticipationActive() {
            return Boolean(this.testSession && !this.testSession.submitted);
        },
        testParticipationCurrentQuestion() {
            const session = this.testSession;
            if (!session?.questions?.length) return null;
            return session.questions[session.currentIndex] ?? null;
        },
        testParticipationCurrentScenario() {
            const question = this.testParticipationCurrentQuestion;
            if (question?.section_type !== "case_scenario") return "";
            return String(question.global_question || "").trim();
        },
        testParticipationClock() {
            const session = this.testSession;
            if (!session) return "00:00";
            const total = Math.max(0, Number(session.remainingSeconds || 0));
            const minutes = Math.floor(total / 60);
            const seconds = total % 60;
            return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
        },
        desktopParticipationAllowed() {
            return Boolean(String(this.desktopParticipationToken || "").trim());
        },
    },
    created() {
        this.syncDesktopParticipationFromUrl();
    },
    watch: {
        testFilterTopic() {
            this.$nextTick(() => {
                if (this.testFilterLevel && !this.testFilterLevelOptions.includes(this.testFilterLevel)) {
                    this.testFilterLevel = "";
                }
                this.syncTestFilterDuration();
            });
        },
        testFilterLevel() {
            this.$nextTick(() => this.syncTestFilterDuration());
        },
    },
    methods: {
        syncTestFilterDuration() {
            const allowed = new Set(this.testFilterDurationOptions.map((m) => String(m)));
            const cur = String(this.testFilterDuration ?? "");
            if (cur !== "" && !allowed.has(cur)) {
                this.testFilterDuration = "";
            }
        },
        clearDashboardTestFilters() {
            this.testFilterTopic = "";
            this.testFilterLevel = "";
            this.testFilterDuration = "";
        },
        emptyProfilePayload(userId = 0) {
            return {
                profile: {
                    user: {
                        id: Number(userId || 0),
                        username: "",
                        email: "",
                        credits: 0,
                    },
                    tests_done: 0,
                    passed_tests: 0,
                    failed_tests: 0,
                    success_rate_percent: 0,
                },
                my_results: [],
            };
        },
        syncDesktopParticipationFromUrl() {
            const storageKey = "desktop_ptoken_v1";
            try {
                const url = new URL(window.location.href);
                const qp = url.searchParams.get("desktop_participation");
                if (qp) {
                    const token = decodeURIComponent(qp).trim();
                    sessionStorage.setItem(storageKey, token);
                    this.desktopParticipationToken = token;
                    url.searchParams.delete("desktop_participation");
                    const qs = url.searchParams.toString();
                    const next = `${url.pathname}${qs ? `?${qs}` : ""}${url.hash}`;
                    window.history.replaceState({}, "", next);
                    return;
                }
            } catch (_e) {
                /* ignore malformed URL */
            }
            try {
                this.desktopParticipationToken = (sessionStorage.getItem(storageKey) || "").trim();
            } catch (_e2) {
                this.desktopParticipationToken = "";
            }
        },
        pathToView(pathname) {
            if (pathname === "/profile") return "profile";
            if (pathname === "/admin") return "admin";
            return "dashboard";
        },
        getProfileTargetUserIdFromLocation() {
            if (window.location.pathname !== "/profile") return 0;
            const raw = new URLSearchParams(window.location.search).get("user_id");
            const parsed = Number(raw);
            return Number.isInteger(parsed) && parsed > 0 ? parsed : 0;
        },
        viewToPath(view) {
            if (view === "profile") {
                if (this.profileTargetUserId > 0) {
                    return `/profile?user_id=${this.profileTargetUserId}`;
                }
                return "/profile";
            }
            if (view === "admin") return "/admin";
            return "/dashboard";
        },
        isAdminRole(role) {
            return role === "admin" || role === "super_admin";
        },
        async openUserProfile(userId) {
            const targetUserId = Number(userId);
            if (!Number.isInteger(targetUserId) || targetUserId <= 0) return;
            await this.setView("profile", false, { profileUserId: targetUserId });
        },
        async openActiveUserFromList(user) {
            if (!user || this.busy) return;
            if (Number(user.id) === Number(this.me?.id)) {
                await this.setView("profile");
                return;
            }
            await this.openUserProfile(user.id);
        },
        async openRecentResultProfile(item) {
            if (!item || this.busy) return;
            const uid = Number(item.user_id);
            if (!Number.isFinite(uid) || uid <= 0) return;
            if (uid === Number(this.me?.id)) {
                await this.setView("profile");
                return;
            }
            await this.openUserProfile(uid);
        },
        isRecentResultAdmin(item) {
            if (!item) return false;
            const fromItem = this.isAdminRole(item.user_role);
            if (fromItem) return true;
            const users = this.dashboard?.social_dashboard?.active_users || [];
            const match = users.find((u) => Number(u.id) === Number(item.user_id));
            return match ? this.isAdminRole(match.role) : false;
        },
        normalizeRole(role) {
            if (typeof role === "string") return role;
            if (role && typeof role === "object" && role.value !== undefined) return String(role.value);
            return "user";
        },
        normalizeDashboardPayload(raw) {
            const payload = raw && typeof raw === "object" ? raw : {};
            const profileSrc = payload.profile || {};
            const userSrc = profileSrc.user || {};
            const socialRaw = payload.social_dashboard || {};
            const social_dashboard = {
                tests: Array.isArray(socialRaw.tests)
                    ? socialRaw.tests.map((t) => ({
                          ...t,
                          id: Number(t.id),
                          duration_seconds: Number(t.duration_seconds ?? 0),
                          passing_percent: Number(t.passing_percent ?? 0),
                          question_count: Number(t.question_count ?? 0),
                      }))
                    : [],
                active_users: Array.isArray(socialRaw.active_users)
                    ? socialRaw.active_users.map((u) => ({
                          ...u,
                          id: Number(u.id),
                          tests_done: Number(u.tests_done ?? 0),
                          success_rate_percent: Number(u.success_rate_percent ?? 0),
                          follower_count: Number(u.follower_count ?? 0),
                          role: this.normalizeRole(u.role),
                      }))
                    : [],
                recent_results: Array.isArray(socialRaw.recent_results)
                    ? socialRaw.recent_results.map((r) => ({
                          ...r,
                          attempt_id: Number(r.attempt_id),
                          user_id: Number(r.user_id),
                          user_role:
                              r.user_role !== undefined && r.user_role !== null
                                  ? this.normalizeRole(r.user_role)
                                  : undefined,
                          score: Number(r.score ?? 0),
                          total_questions: Number(r.total_questions ?? 0),
                          success_percent: Number(r.success_percent ?? 0),
                          passed: Boolean(r.passed),
                      }))
                    : [],
                following_user_ids: Array.isArray(socialRaw.following_user_ids)
                    ? socialRaw.following_user_ids.map((id) => Number(id)).filter((id) => Number.isFinite(id))
                    : [],
            };
            const profile = {
                user: {
                    id: Number(userSrc.id ?? 0),
                    username: String(userSrc.username ?? ""),
                    email: String(userSrc.email ?? ""),
                    credits: Number(userSrc.credits ?? 0),
                    role: this.normalizeRole(userSrc.role),
                    is_active: userSrc.is_active !== false,
                },
                tests_done: Number(profileSrc.tests_done ?? 0),
                passed_tests: Number(profileSrc.passed_tests ?? 0),
                failed_tests: Number(profileSrc.failed_tests ?? 0),
                success_rate_percent: Number(profileSrc.success_rate_percent ?? 0),
            };
            const comments = payload.comments_by_test;
            const comments_by_test =
                comments && typeof comments === "object" && !Array.isArray(comments) ? comments : {};
            return {
                profile,
                social_dashboard,
                comments_by_test,
                web_test_enabled: Boolean(payload.web_test_enabled),
            };
        },
        clearNotices() {
            this.error = "";
            this.success = "";
        },
        resetPreloadState() {
            this.preloadStatus.dashboard = false;
            this.preloadStatus.profile = false;
            this.preloadStatus.admin = false;
            this.preloadBusy.dashboard = false;
            this.preloadBusy.profile = false;
            this.preloadBusy.admin = false;
            this.preloadFetchedAt.dashboard = 0;
            this.preloadFetchedAt.profile = 0;
            this.preloadFetchedAt.admin = 0;
            this.admin.selectedUserStatsFetchedAt = 0;
        },
        isViewDataStale(view) {
            if (!this.preloadStatus[view]) return true;
            const fetchedAt = Number(this.preloadFetchedAt[view] || 0);
            if (!fetchedAt) return true;
            return Date.now() - fetchedAt > this.preloadTtlMs;
        },
        markViewDataFresh(view) {
            this.preloadStatus[view] = true;
            this.preloadFetchedAt[view] = Date.now();
        },
        async loadViewData(view, options = {}) {
            if (view === "profile") {
                await this.loadProfile(options);
                return;
            }
            if (view === "admin") {
                await this.loadAdmin(options);
                return;
            }
            await this.loadDashboard(options);
        },
        async preloadViewData(view, options = {}) {
            const { force = false } = options;
            if (!this.authenticated) return;
            if (view === "admin" && !this.isAdmin) return;
            if (this.preloadBusy[view]) return;
            if (!force && !this.isViewDataStale(view)) return;

            this.preloadBusy[view] = true;
            try {
                await this.loadViewData(view, { silent: true });
            } finally {
                this.preloadBusy[view] = false;
            }
        },
        preloadInactiveViews() {
            if (!this.authenticated) return;
            const viewsToPreload = ["dashboard", "profile"];
            if (this.isAdmin) viewsToPreload.push("admin");
            for (const nextView of viewsToPreload) {
                if (nextView === this.view) continue;
                this.preloadViewData(nextView).catch(() => {});
            }
        },
        formatDate(value) {
            if (!value) return "-";
            try {
                return new Date(value).toLocaleString();
            } catch (_err) {
                return String(value);
            }
        },
        userInitials(username) {
            const text = String(username || "").trim();
            if (!text) return "?";
            const parts = text.split(/\s+/).filter(Boolean);
            if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
            return `${parts[0][0]}${parts[parts.length - 1][0]}`.toUpperCase();
        },
        avatarStyle(username) {
            const text = String(username || "");
            let hash = 0;
            for (let i = 0; i < text.length; i += 1) {
                hash = (hash << 5) - hash + text.charCodeAt(i);
                hash |= 0;
            }
            const hue = Math.abs(hash) % 360;
            const nextHue = (hue + 32) % 360;
            return {
                background: `linear-gradient(135deg, hsl(${hue} 70% 56%), hsl(${nextHue} 70% 44%))`,
            };
        },
        testCardHashSeed(test) {
            let h = Number(test?.id ?? 0) >>> 0;
            const s = `${String(test?.topic_name ?? "")}\0${String(test?.level_name ?? "")}`;
            for (let i = 0; i < s.length; i += 1) {
                h = Math.imul(31, h) + s.charCodeAt(i);
                h >>>= 0;
            }
            return h || 1;
        },
        testCardGeometricBackground(test) {
            let state = this.testCardHashSeed(test);
            const rnd = () => {
                state = Math.imul(1664525, state) + 1013904223;
                return (state >>> 0) / 2 ** 32;
            };
            const h1 = Math.floor(rnd() * 360);
            const h2 = Math.floor(h1 + 28 + rnd() * 92) % 360;
            const h3 = Math.floor(h2 + 40 + rnd() * 88) % 360;
            const xp1 = `${(8 + rnd() * 76).toFixed(1)}%`;
            const yp1 = `${(10 + rnd() * 70).toFixed(1)}%`;
            const xp2 = `${(62 + rnd() * 32).toFixed(1)}%`;
            const yp2 = `${(12 + rnd() * 55).toFixed(1)}%`;
            const ang1 = Math.floor(rnd() * 140);
            const ang2 = Math.floor(55 + rnd() * 115);
            const ang3 = Math.floor(rnd() * 180);

            const layers = [
                `linear-gradient(
                    ${165 + Math.floor(rnd() * 20)}deg,
                    rgba(255, 255, 255, 0.965) 0%,
                    rgba(255, 255, 255, 0.72) 48%,
                    rgba(253, 252, 255, 0.78) 100%
                )`,
                `conic-gradient(
                    from ${ang1 + 200 + Math.floor(rnd() * 40)}deg at ${xp1} ${yp1},
                    hsla(${h2} 70% 78% / 0.42) 0deg,
                    transparent 42deg,
                    hsla(${h1} 75% 80% / 0.38) 88deg,
                    transparent 148deg,
                    hsla(${h3} 65% 82% / 0.34) 210deg,
                    transparent 296deg,
                    hsla(${h2} 68% 84% / 0.26) 330deg,
                    transparent 360deg
                )`,
                `linear-gradient(
                    ${ang2 + 35}deg,
                    hsla(${h1} 62% 90% / 0.92) 0%,
                    transparent 46%,
                    hsla(${h3} 58% 88% / 0.72) 100%
                )`,
                `radial-gradient(
                    ellipse ${`${(55 + rnd() * 45).toFixed(0)}%`} ${`${(35 + rnd() * 40).toFixed(0)}%`}
                    at ${xp2} ${yp2},
                    hsla(${h2} 78% 86% / 0.62) 0%,
                    transparent 58%
                )`,
                `repeating-linear-gradient(
                    ${ang3 + 15}deg,
                    transparent 0 11px,
                    hsla(${h1} 50% 50% / 0.048) 11px 12px,
                    transparent 12px 28px,
                    hsla(${h3} 45% 50% / 0.036) 28px 29px,
                    transparent 29px 40px
                )`,
                `linear-gradient(
                    ${-40 + Math.floor(rnd() * 100)}deg,
                    transparent 52%,
                    hsla(${h2} 70% 70% / 0.16) 100%
                )`,
            ].map((layer) => layer.replace(/\s+/g, " ").trim());

            return {
                backgroundColor: `hsl(${h1} 42% 98%)`,
                backgroundImage: layers.join(", "),
            };
        },
        profileResultGeoStyle(item) {
            return this.testCardGeometricBackground({
                id: item.attempt_id,
                topic_name: item.topic_name,
                level_name: item.level_name,
            });
        },
        stopParticipationTimer() {
            const handle = this.testSession?.timerHandle;
            if (handle != null) {
                clearInterval(handle);
            }
            if (this.testSession) {
                this.testSession.timerHandle = null;
            }
        },
        clearParticipationSession() {
            this.stopParticipationTimer();
            this.testSession = null;
        },
        recordParticipationViolation(reason) {
            const session = this.testSession;
            if (!session || session.submitted || session.disqualifying || session.antiCheatSuppressed) return;
            const now = Date.now();
            if (now - Number(session.lastViolationAt || 0) < 1500) return;
            session.lastViolationAt = now;
            session.antiCheatWarnings = Math.min(Number(session.maxWarnings || 5), Number(session.antiCheatWarnings || 0) + 1);
            session.lastViolationReason = reason;
            if (session.antiCheatWarnings >= Number(session.maxWarnings || 5)) {
                void this.disqualifyParticipationTest(reason);
                return;
            }
        },
        handleParticipationVisibilityChange() {
            if (document.visibilityState === "hidden") {
                this.recordParticipationViolation("Do not switch tabs or hide the test window.");
            }
        },
        handleParticipationWindowBlur() {
            this.recordParticipationViolation("Do not leave the test window.");
        },
        handleParticipationBeforeUnload(event) {
            if (!this.testParticipationActive) return;
            this.recordParticipationViolation("Do not close or reload the test window.");
            event.preventDefault();
            event.returnValue = "A test is in progress. Closing this window can disqualify the attempt.";
            return event.returnValue;
        },
        handleParticipationPageHide() {
            const session = this.testSession;
            if (!session || session.submitted) return;
            const attemptId = Number(session.attemptId || 0);
            if (!attemptId) return;
            try {
                if (navigator.sendBeacon) {
                    navigator.sendBeacon(`/webapi/tests/disqualify/${attemptId}`, new Blob([], { type: "text/plain" }));
                } else {
                    fetch(`/webapi/tests/disqualify/${attemptId}`, {
                        method: "POST",
                        credentials: "same-origin",
                        keepalive: true,
                    }).catch(() => {});
                }
            } catch (_err) {
                /* best-effort cleanup when the page is leaving */
            }
        },
        installParticipationAntiCheat() {
            document.addEventListener("visibilitychange", this.handleParticipationVisibilityChange);
            window.addEventListener("blur", this.handleParticipationWindowBlur);
            window.addEventListener("beforeunload", this.handleParticipationBeforeUnload);
            window.addEventListener("pagehide", this.handleParticipationPageHide);
        },
        runParticipationTimerLoop() {
            const session = this.testSession;
            if (!session || session.submitted) return;
            if (session.remainingSeconds <= 0) return;
            session.remainingSeconds -= 1;
            if (session.remainingSeconds <= 0) {
                this.stopParticipationTimer();
                void this.submitParticipationTest(true);
            }
        },
        startParticipationTimer() {
            if (!this.testSession || this.testSession.submitted) return;
            this.stopParticipationTimer();
            if (this.testSession.remainingSeconds <= 0) {
                void this.submitParticipationTest(true);
                return;
            }
            this.testSession.timerHandle = setInterval(() => this.runParticipationTimerLoop(), 1000);
        },
        participationSelectOption(questionId, optionIndex) {
            if (!this.testSession || this.testSession.submitted) return;
            const question = (this.testSession.questions || []).find((item) => Number(item.id) === Number(questionId));
            if (question?.allow_multiple) {
                const current = Array.isArray(this.testSession.answers[Number(questionId)])
                    ? this.testSession.answers[Number(questionId)].slice()
                    : [];
                const option = Number(optionIndex);
                const next = current.includes(option) ? current.filter((item) => item !== option) : [...current, option];
                this.testSession.answers[Number(questionId)] = next.sort((a, b) => a - b);
                return;
            }
            this.testSession.answers[Number(questionId)] = Number(optionIndex);
        },
        participationOptionPicked(questionId, optionIndex) {
            const question = (this.testSession?.questions || []).find((item) => Number(item.id) === Number(questionId));
            const answer = this.testSession?.answers?.[Number(questionId)];
            if (question?.allow_multiple) {
                return Array.isArray(answer) && answer.includes(Number(optionIndex));
            }
            return answer === Number(optionIndex);
        },
        participationGoPrev() {
            if (!this.testSession?.questions?.length) return;
            if (this.testSession.currentIndex > 0) {
                this.testSession.currentIndex -= 1;
            }
        },
        participationGoNext() {
            if (!this.testSession?.questions?.length) return;
            if (this.testSession.currentIndex < this.testSession.questions.length - 1) {
                this.testSession.currentIndex += 1;
            }
        },
        async startParticipateInTest(testRow) {
            if (!testRow || this.busy || this.testSession) return;
            if (!this.authenticated) return;
            const questionsCount = Number(testRow.question_count ?? 0);
            if (questionsCount < 1) {
                this.error = "This test has no questions yet.";
                return;
            }
            const label = `${testRow.topic_name} - ${testRow.level_name}`;
            const ok = window.confirm(
                `Start "${label}" now? One credit is deducted when the session begins.`,
            );
            if (!ok) return;
            this.clearNotices();
            this.busy = true;
            try {
                const data = await this.request("POST", `/webapi/tests/start/${testRow.id}`, null);
                const questions = Array.isArray(data.questions) ? data.questions : [];
                this.testSession = {
                    submitted: false,
                    attemptId: Number(data.attempt_id),
                    testConfigId: Number(testRow.id),
                    title: label,
                    passingPercent: Number(data.passing_percent ?? testRow.passing_percent ?? 60),
                    remainingSeconds: Math.max(0, Number(data.duration_seconds ?? testRow.duration_seconds ?? 0)),
                    questions,
                    currentIndex: 0,
                    answers: {},
                    timerHandle: null,
                    antiCheatWarnings: 0,
                    maxWarnings: 5,
                    lastViolationReason: "",
                    lastViolationAt: 0,
                    antiCheatSuppressed: false,
                    disqualifying: false,
                };
                if (this.me && Number.isFinite(Number(data.remaining_credits))) {
                    this.me.credits = Number(data.remaining_credits);
                }
                this.startParticipationTimer();
                this.success = `Test started. Pass at or above ${this.testSession.passingPercent.toFixed(2)}%.`;
            } catch (error) {
                this.error = error.message;
            } finally {
                this.busy = false;
            }
        },
        async submitParticipationTest(forced = false) {
            const session = this.testSession;
            if (!session || session.submitted || this.busy) return;
            if (!forced) {
                session.antiCheatSuppressed = true;
                let confirmed = false;
                try {
                    confirmed = window.confirm(
                        "Submit all answers now? Any question without a selection counts as incorrect.",
                    );
                } finally {
                    window.setTimeout(() => {
                        if (session && !session.submitted) session.antiCheatSuppressed = false;
                    }, 500);
                }
                if (!confirmed) return;
            }
            const attemptId = session.attemptId;
            const remainingSnap = Number(session.remainingSeconds || 0);
            const answersPayload = {};
            for (const [key, value] of Object.entries(session.answers)) {
                const qid = Number(key);
                if (Number.isFinite(qid)) {
                    if (Array.isArray(value)) {
                        answersPayload[String(qid)] = value
                            .map((item) => Number(item))
                            .filter((item) => Number.isInteger(item) && item >= 0);
                    } else {
                        answersPayload[String(qid)] = Number(value);
                    }
                }
            }
            this.busy = true;
            this.stopParticipationTimer();
            try {
                const data = await this.request("POST", `/webapi/tests/submit/${attemptId}`, {
                    answers: answersPayload,
                });
                session.submitted = true;
                const status = data.passed ? "Passed" : "Failed";
                this.success = `${status} · Score ${data.score}/${data.total_questions} (${Number(
                    data.success_percent,
                ).toFixed(2)}%). Credits: ${data.remaining_credits}.`;
                if (this.me && Number.isFinite(Number(data.remaining_credits))) {
                    this.me.credits = Number(data.remaining_credits);
                }
                this.clearParticipationSession();
                await this.loadDashboard({ silent: true });
            } catch (error) {
                this.error = error.message;
                if (
                    this.testSession &&
                    this.testSession.attemptId === attemptId &&
                    !this.testSession.submitted &&
                    !forced &&
                    remainingSnap > 0
                ) {
                    this.startParticipationTimer();
                }
            } finally {
                this.busy = false;
            }
        },
        async disqualifyParticipationTest(reason = "Anti-cheat warning limit reached.") {
            const session = this.testSession;
            if (!session || session.submitted || session.disqualifying) return;
            const attemptId = Number(session.attemptId || 0);
            if (!attemptId) return;
            session.disqualifying = true;
            this.busy = true;
            this.stopParticipationTimer();
            try {
                const data = await this.request("POST", `/webapi/tests/disqualify/${attemptId}`, null);
                session.submitted = true;
                this.error = `Disqualified: ${reason}`;
                if (this.me && Number.isFinite(Number(data.remaining_credits))) {
                    this.me.credits = Number(data.remaining_credits);
                }
                this.clearParticipationSession();
                await this.loadDashboard({ silent: true });
            } catch (error) {
                this.error = error.message;
                session.disqualifying = false;
            } finally {
                this.busy = false;
            }
        },
        commentVisibleCount(testId) {
            return this.commentVisibleCounts[testId] || 2;
        },
        visibleComments(testId) {
            const comments = this.dashboard.comments_by_test[testId] || [];
            const visibleCount = this.commentVisibleCount(testId);
            return comments.slice(0, visibleCount);
        },
        hasMoreComments(testId) {
            const comments = this.dashboard.comments_by_test[testId] || [];
            return comments.length > this.commentVisibleCount(testId);
        },
        showMoreComments(testId) {
            const comments = this.dashboard.comments_by_test[testId] || [];
            const current = this.commentVisibleCount(testId);
            this.commentVisibleCounts[testId] = Math.min(comments.length, current + 2);
        },
        commentCountForTest(testId) {
            const list = this.dashboard.comments_by_test[testId];
            return Array.isArray(list) ? list.length : 0;
        },
        latestCommentForTest(testId) {
            const list = this.dashboard.comments_by_test[testId];
            if (!Array.isArray(list) || !list.length) return null;
            let best = list[0];
            let bestMs = new Date(best.created_at || 0).getTime();
            for (let i = 1; i < list.length; i += 1) {
                const item = list[i];
                const ms = new Date(item.created_at || 0).getTime();
                if (ms >= bestMs) {
                    best = item;
                    bestMs = ms;
                }
            }
            return best;
        },
        latestCommentPreviewForTest(testId, maxLen = 90) {
            const c = this.latestCommentForTest(testId);
            if (!c) return "";
            const text = String(c.content || "")
                .trim()
                .replace(/\s+/g, " ");
            if (!text) return "";
            if (text.length <= maxLen) return text;
            return `${text.slice(0, maxLen).trimEnd()}…`;
        },
        isCommentSectionOpen(testId) {
            return Boolean(this.commentSectionExpanded[String(testId)]);
        },
        toggleCommentSection(testId) {
            const key = String(testId);
            this.commentSectionExpanded[key] = !this.commentSectionExpanded[key];
        },
        selectAdminTest(testConfigId) {
            this.admin.selectedTestConfigId = Number(testConfigId) || 0;
            this.admin.sectionForm.test_config_id = Number(testConfigId) || 0;
        },
        normalizeAdminSection(section) {
            const rawType = String(section?.section_type || "").trim().toLowerCase().replace("-", "_");
            const hasScenario = Boolean(String(section?.global_question || "").trim());
            const sectionType = rawType || (hasScenario ? "case_scenario" : "regular");
            return {
                ...section,
                section_type: sectionType === "case_scenario" ? "case_scenario" : "regular",
                global_question: String(section?.global_question || ""),
                requires_full_score: Boolean(section?.requires_full_score),
            };
        },
        async selectAdminUser(userId) {
            const nextUserId = Number(userId) || 0;
            if (Number(this.admin.selectedUserId || 0) !== nextUserId) {
                this.admin.selectedUserStats = null;
                this.admin.selectedUserStatsFetchedAt = 0;
            }
            this.admin.selectedUserId = nextUserId;
            if (this.admin.activeTab === "stats" || this.admin.userFormMode === "update") {
                await this.selectUser();
            }
        },
        async setAdminTab(tab) {
            this.admin.activeTab = tab;
            if (tab === "stats" && this.admin.selectedUserId) {
                await this.selectUser();
            }
        },
        optionLetter(index) {
            return String.fromCharCode(65 + Number(index));
        },
        questionOptionAt(question, optionIndex) {
            if (!Array.isArray(question?.options)) return "-";
            return question.options[optionIndex] || "-";
        },
        getQuestionCorrectIndices(question) {
            if (Array.isArray(question?.correct_indices) && question.correct_indices.length) {
                return Array.from(
                    new Set(
                        question.correct_indices
                            .map((item) => Number(item))
                            .filter((item) => Number.isInteger(item) && item >= 0),
                    ),
                ).sort((a, b) => a - b);
            }
            if (Number.isInteger(question?.correct_index) && question.correct_index >= 0) {
                return [Number(question.correct_index)];
            }
            return [];
        },
        questionCorrectText(question) {
            const options = Array.isArray(question?.options) ? question.options : [];
            const indices = this.getQuestionCorrectIndices(question);
            if (!indices.length) return "-";
            const labels = indices.map((index) => options[index] || `Option ${this.optionLetter(index)}`);
            return labels.join(", ");
        },
        answerListText(items) {
            if (!Array.isArray(items) || !items.length) return "No answer";
            return items.join(", ");
        },
        attemptPercent(attempt) {
            const total = Number(attempt?.total_questions || 0);
            if (total <= 0) return "0.00";
            return ((Number(attempt?.score || 0) / total) * 100).toFixed(2);
        },
        sectionName(sectionId) {
            const id = Number(sectionId || 0);
            const section = (this.admin.sections || []).find((item) => Number(item.id) === id);
            return section ? section.name : "Unsectioned";
        },
        resetSectionForm() {
            this.admin.sectionForm = {
                id: 0,
                test_config_id: Number(this.activeAdminTestConfig?.id || 0),
                name: "",
                select_count: 1,
                points_per_question: 1,
                requires_full_score: false,
                section_type: "regular",
                global_question: "",
            };
        },
        resetAdminTestForm() {
            this.admin.testForm = {
                id: 0,
                topic_name: "",
                level_name: "",
                duration_minutes: 15,
                passing_percent: 60,
                is_active: true,
            };
        },
        openCreateTestMode() {
            this.admin.testFormMode = "create";
            this.resetAdminTestForm();
            this.admin.testModalOpen = true;
        },
        openUpdateTestMode() {
            if (!this.admin.test_configs.length) {
                this.error = "No tests available to update.";
                return;
            }
            const target = this.activeAdminTestConfig || this.admin.test_configs[0];
            this.prepareEditTest(target);
            this.admin.testModalOpen = true;
        },
        closeTestModal() {
            this.admin.testModalOpen = false;
        },
        openCreateUserMode() {
            this.admin.userFormMode = "create";
            this.admin.selectedUserStats = null;
            this.admin.createUser = {
                username: "",
                email: "",
                password: "",
                role: "user",
                credits: 0,
            };
            this.admin.userModalOpen = true;
        },
        async openUpdateUserMode() {
            const target = this.activeAdminUser;
            if (!target) {
                this.error = "No users available to edit.";
                return;
            }
            this.admin.userFormMode = "update";
            this.admin.userModalOpen = true;
            await this.selectAdminUser(target.id);
        },
        closeUserModal() {
            this.admin.userModalOpen = false;
            this.admin.userFormMode = "create";
        },
        prepareEditTest(config) {
            this.admin.testFormMode = "update";
            this.selectAdminTest(config.id);
            this.admin.testForm = {
                id: config.id,
                topic_name: config.topic_name,
                level_name: config.level_name,
                duration_minutes: Number(config.duration_minutes),
                passing_percent: Number(config.passing_percent),
                is_active: Boolean(config.is_active),
            };
        },
        openConfirmModal(title, message, action) {
            this.admin.confirmModal = { title, message, action };
            this.admin.confirmModalOpen = true;
        },
        closeConfirmModal() {
            this.admin.confirmModalOpen = false;
            this.admin.confirmModal = { title: "", message: "", action: "" };
        },
        async confirmModalAction() {
            const { action } = this.admin.confirmModal;
            this.closeConfirmModal();
            if (action === "delete-test") {
                await this.deleteAdminTest();
                return;
            }
            if (action === "delete-user") {
                await this.deleteAdminUser();
                return;
            }
            if (action === "delete-question") {
                await this.deleteAdminQuestion();
                return;
            }
            if (action === "delete-section") {
                await this.deleteAdminSection();
            }
        },
        requestDeleteAdminTest() {
            const target = this.activeAdminTestConfig;
            if (!target) return;
            this.openConfirmModal(
                "Delete Test",
                `Delete "${target.topic_name} - ${target.level_name}"? This action cannot be undone.`,
                "delete-test",
            );
        },
        requestDeleteAdminUser() {
            const target = this.activeAdminUser;
            if (!target) return;
            this.openConfirmModal(
                "Delete User",
                `Delete user "${target.username}"? This action cannot be undone.`,
                "delete-user",
            );
        },
        requestDeleteAdminQuestion() {
            if (!this.admin.questionForm.id) return;
            this.openConfirmModal(
                "Delete Question",
                "Delete this question? This action cannot be undone.",
                "delete-question",
            );
        },
        requestDeleteAdminSection(section) {
            if (!section?.id) return;
            this.admin.sectionForm = {
                id: Number(section.id),
                test_config_id: Number(section.test_config_id),
                name: String(section.name || ""),
                select_count: Number(section.select_count || 1),
                points_per_question: Number(section.points_per_question || 1),
                section_type: String(section.section_type || "regular"),
                global_question: String(section.global_question || ""),
                requires_full_score: Boolean(section.requires_full_score),
            };
            this.openConfirmModal(
                "Delete Section",
                `Delete section "${section.name}"? Questions in it will become unsectioned.`,
                "delete-section",
            );
        },
        setQuestionTarget(testConfigId) {
            this.admin.questionForm.test_config_id = Number(testConfigId) || 0;
        },
        resetQuestionForm() {
            const keepTestId = Number(this.admin.questionForm.test_config_id) || 0;
            this.admin.questionForm = {
                id: 0,
                test_config_id: keepTestId,
                section_id: null,
                question_text: "",
                options: ["", "", "", ""],
                correct_indices: [],
            };
        },
        openAddQuestionModal(config) {
            this.admin.questionModalMode = "create";
            this.setQuestionTarget(config?.id);
            this.resetQuestionForm();
            this.admin.questionModalOpen = true;
        },
        openEditQuestionModal(question) {
            const options = Array.isArray(question?.options) ? question.options.map((item) => String(item)) : ["", ""];
            this.admin.questionModalMode = "edit";
            this.admin.questionForm = {
                id: Number(question?.id) || 0,
                test_config_id: Number(question?.test_config_id) || Number(this.activeAdminTestConfig?.id) || 0,
                section_id: question?.section_id ? Number(question.section_id) : null,
                question_text: String(question?.question_text || ""),
                options: options.length >= 2 ? options : ["", ""],
                correct_indices: this.getQuestionCorrectIndices(question),
            };
            this.admin.questionModalOpen = true;
        },
        closeQuestionModal() {
            this.admin.questionModalOpen = false;
        },
        isCorrectOption(index) {
            return this.admin.questionForm.correct_indices.includes(index);
        },
        toggleCorrectOption(index, checked) {
            const current = new Set(this.admin.questionForm.correct_indices);
            if (checked) {
                current.add(index);
            } else {
                current.delete(index);
            }
            this.admin.questionForm.correct_indices = Array.from(current).sort((a, b) => a - b);
        },
        addQuestionOption() {
            if (this.admin.questionForm.options.length >= 10) return;
            this.admin.questionForm.options.push("");
        },
        removeQuestionOption(index) {
            if (this.admin.questionForm.options.length <= 2) return;
            this.admin.questionForm.options.splice(index, 1);
            this.admin.questionForm.correct_indices = this.admin.questionForm.correct_indices
                .filter((item) => item !== index)
                .map((item) => (item > index ? item - 1 : item))
                .sort((a, b) => a - b);
        },
        validateQuestionForm() {
            const form = this.admin.questionForm;
            const cleanedOptions = form.options.map((item) => String(item).trim());
            if (!form.test_config_id) {
                this.error = "Select a test before saving a question.";
                return null;
            }
            if (cleanedOptions.length < 2) {
                this.error = "At least 2 options are required.";
                return null;
            }
            if (!form.question_text.trim() || cleanedOptions.some((item) => !item)) {
                this.error = "Question text and all options are required.";
                return null;
            }
            const uniqueOptionsCount = new Set(cleanedOptions.map((item) => item.toLowerCase())).size;
            if (uniqueOptionsCount !== cleanedOptions.length) {
                this.error = "Question options must be unique.";
                return null;
            }
            const selectedCorrect = Array.from(new Set(form.correct_indices))
                .filter((item) => Number.isInteger(item) && item >= 0 && item < cleanedOptions.length)
                .sort((a, b) => a - b);
            if (!selectedCorrect.length) {
                this.error = "Select at least one correct answer.";
                return null;
            }
            return {
                test_config_id: Number(form.test_config_id),
                section_id: form.section_id ? Number(form.section_id) : null,
                question_text: form.question_text,
                options: cleanedOptions,
                correct_indices: selectedCorrect,
            };
        },
        async submitAdminQuestion() {
            this.clearNotices();
            const payload = this.validateQuestionForm();
            if (!payload) return;
            this.busy = true;
            try {
                if (this.admin.questionModalMode === "edit" && this.admin.questionForm.id) {
                    await this.request("PATCH", `/webapi/admin/questions/${this.admin.questionForm.id}`, {
                        section_id: payload.section_id,
                        question_text: payload.question_text,
                        options: payload.options,
                        correct_indices: payload.correct_indices,
                    });
                    this.success = "Question updated.";
                } else {
                    await this.request("POST", "/webapi/admin/questions", payload);
                    this.success = "Question added.";
                }
                await this.loadAdmin();
                this.closeQuestionModal();
            } catch (error) {
                this.error = error.message;
            } finally {
                this.busy = false;
            }
        },
        async deleteAdminQuestion() {
            if (!this.admin.questionForm.id) return;
            this.clearNotices();
            this.busy = true;
            try {
                await this.request("DELETE", `/webapi/admin/questions/${this.admin.questionForm.id}`);
                this.success = "Question deleted.";
                await this.loadAdmin();
                this.closeQuestionModal();
            } catch (error) {
                this.error = error.message;
            } finally {
                this.busy = false;
            }
        },
        async submitAdminSection(section = null) {
            this.clearNotices();
            const form = section
                ? {
                      id: Number(section.id || 0),
                      test_config_id: Number(section.test_config_id || this.activeAdminTestConfig?.id || 0),
                      name: String(section.name || ""),
                      select_count: Number(section.select_count || 1),
                      points_per_question: Number(section.points_per_question || 1),
                      order_index: Number(section.order_index || 0),
                      requires_full_score: Boolean(section.requires_full_score),
                      section_type: String(section.section_type || "regular"),
                      global_question: String(section.global_question || ""),
                  }
                : this.admin.sectionForm;
            if (!form.test_config_id) {
                this.error = "Select a test before saving a section.";
                return;
            }
            if (!String(form.name || "").trim()) {
                this.error = "Section name is required.";
                return;
            }
            if (Number(form.select_count) < 1 || Number(form.points_per_question) < 1) {
                this.error = "Select count and worth must be at least 1.";
                return;
            }
            const sectionTypeRaw = String(form.section_type || "regular").trim().toLowerCase().replace("-", "_");
            const sectionType = sectionTypeRaw === "case_scenario" ? "case_scenario" : "regular";
            const globalQuestion = String(form.global_question || "").trim();
            if (sectionType === "case_scenario" && !globalQuestion) {
                this.error = "Global question is required for case-scenario sections.";
                return;
            }
            const payload = {
                test_config_id: Number(form.test_config_id),
                name: String(form.name).trim(),
                select_count: Number(form.select_count),
                points_per_question: Number(form.points_per_question),
                requires_full_score: Boolean(form.requires_full_score),
                section_type: sectionType,
                global_question: sectionType === "case_scenario" ? globalQuestion : null,
            };
            this.busy = true;
            try {
                let savedSection = null;
                if (form.id) {
                    savedSection = await this.request("PATCH", `/webapi/admin/test-sections/${form.id}`, {
                        name: payload.name,
                        select_count: payload.select_count,
                        points_per_question: payload.points_per_question,
                        requires_full_score: payload.requires_full_score,
                        section_type: payload.section_type,
                        global_question: payload.global_question,
                    });
                    this.success = "Section updated.";
                } else {
                    savedSection = await this.request("POST", "/webapi/admin/test-sections", payload);
                    this.success = "Section added.";
                    this.resetSectionForm();
                }
                await this.loadAdmin();
                if (savedSection?.id) {
                    const normalizedSaved = this.normalizeAdminSection({
                        ...savedSection,
                        section_type: payload.section_type,
                        global_question: payload.global_question || savedSection.global_question,
                    });
                    const savedId = Number(normalizedSaved.id);
                    const exists = this.admin.sections.some((item) => Number(item.id) === savedId);
                    this.admin.sections = exists
                        ? this.admin.sections.map((item) => (Number(item.id) === savedId ? { ...item, ...normalizedSaved } : item))
                        : [...this.admin.sections, normalizedSaved];
                }
            } catch (error) {
                this.error = error.message;
            } finally {
                this.busy = false;
            }
        },
        adminSectionDragStart(section) {
            this.admin.draggingSectionId = Number(section?.id || 0);
        },
        adminSectionDragEnd() {
            this.admin.draggingSectionId = 0;
        },
        async dropAdminSection(targetSection) {
            const draggedId = Number(this.admin.draggingSectionId || 0);
            const targetId = Number(targetSection?.id || 0);
            if (!draggedId || !targetId || draggedId === targetId || this.busy) return;
            const sections = this.activeAdminTestSections;
            const fromIndex = sections.findIndex((section) => Number(section.id) === draggedId);
            const toIndex = sections.findIndex((section) => Number(section.id) === targetId);
            if (fromIndex < 0 || toIndex < 0) return;
            const [moved] = sections.splice(fromIndex, 1);
            sections.splice(toIndex, 0, moved);
            const orderIds = sections.map((section) => Number(section.id));
            const orderMap = new Map(orderIds.map((id, index) => [id, index + 1]));
            this.admin.sections = this.admin.sections.map((section) => {
                const order = orderMap.get(Number(section.id));
                return order ? { ...section, order_index: order } : section;
            });
            this.admin.draggingSectionId = 0;
            this.busy = true;
            try {
                await this.request(
                    "PATCH",
                    `/webapi/admin/test-configs/${this.activeAdminTestConfig.id}/sections/reorder`,
                    { section_ids: orderIds },
                );
                await this.loadAdmin({ silent: true });
            } catch (error) {
                this.error = error.message;
                await this.loadAdmin({ silent: true });
            } finally {
                this.busy = false;
            }
        },
        async deleteAdminSection() {
            const sectionId = Number(this.admin.sectionForm.id || 0);
            if (!sectionId) return;
            this.clearNotices();
            this.busy = true;
            try {
                await this.request("DELETE", `/webapi/admin/test-sections/${sectionId}`);
                this.success = "Section deleted.";
                this.resetSectionForm();
                await this.loadAdmin();
            } catch (error) {
                this.error = error.message;
            } finally {
                this.busy = false;
            }
        },
        async deleteAdminTest() {
            const target = this.activeAdminTestConfig;
            if (!target) return;
            this.clearNotices();
            this.busy = true;
            try {
                await this.request("DELETE", `/webapi/admin/test-configs/${target.id}`);
                this.success = "Test deleted.";
                await this.loadAdmin();
                this.admin.testFormMode = "create";
                this.resetAdminTestForm();
                this.admin.testModalOpen = false;
            } catch (error) {
                this.error = error.message;
            } finally {
                this.busy = false;
            }
        },
        async deleteAdminUser() {
            const target = this.activeAdminUser;
            if (!target) return;
            this.clearNotices();
            this.busy = true;
            try {
                await this.request("DELETE", `/webapi/admin/users/${target.id}`);
                this.success = "User deleted.";
                this.admin.selectedUserStats = null;
                await this.loadAdmin();
                if (this.admin.userFormMode === "update" && this.activeAdminUser) {
                    await this.selectAdminUser(this.activeAdminUser.id);
                }
            } catch (error) {
                this.error = error.message;
            } finally {
                this.busy = false;
            }
        },
        async saveAdminTest() {
            this.clearNotices();
            const form = this.admin.testForm;
            if (!form.topic_name.trim() || !form.level_name.trim()) {
                this.error = "Topic and level are required.";
                return;
            }
            this.busy = true;
            try {
                if (this.admin.testFormMode === "update" && form.id) {
                    await this.request("PATCH", `/webapi/admin/test-configs/${form.id}`, {
                        topic_name: form.topic_name,
                        level_name: form.level_name,
                        duration_minutes: Number(form.duration_minutes),
                        passing_percent: Number(form.passing_percent),
                        is_active: Boolean(form.is_active),
                    });
                    this.success = "Test updated.";
                    await this.loadAdmin();
                    const fresh = this.admin.test_configs.find((item) => item.id === form.id);
                    if (fresh) this.prepareEditTest(fresh);
                } else {
                    const created = await this.request("POST", "/webapi/admin/test-configs", {
                        topic_name: form.topic_name,
                        level_name: form.level_name,
                        duration_minutes: Number(form.duration_minutes),
                        passing_percent: Number(form.passing_percent),
                        is_active: Boolean(form.is_active),
                    });
                    this.success = "Test created.";
                    await this.loadAdmin();
                    const createdId = Number(created?.id || 0);
                    const fresh =
                        this.admin.test_configs.find((item) => item.id === createdId) ||
                        this.admin.test_configs.find(
                            (item) =>
                                String(item.topic_name).trim().toLowerCase() === form.topic_name.trim().toLowerCase() &&
                                String(item.level_name).trim().toLowerCase() === form.level_name.trim().toLowerCase(),
                        );
                    if (fresh) {
                        this.prepareEditTest(fresh);
                        this.setQuestionTarget(fresh.id);
                    } else {
                        this.admin.testFormMode = "create";
                        this.resetAdminTestForm();
                    }
                }
                this.closeTestModal();
            } catch (error) {
                this.error = error.message;
            } finally {
                this.busy = false;
            }
        },
        extractErrorDetail(data) {
            const detail = data?.detail;
            if (Array.isArray(detail)) {
                const messages = detail
                    .map((item) => {
                        if (typeof item === "string") return item;
                        if (!item || typeof item !== "object") return "";
                        const locParts = Array.isArray(item.loc)
                            ? item.loc.filter((part) => part !== "body").map((part) => String(part))
                            : [];
                        const location = locParts.join(".");
                        const message = String(item.msg || "Invalid value.");
                        return location ? `${location}: ${message}` : message;
                    })
                    .filter(Boolean);
                return messages.join("; ");
            }
            if (typeof detail === "string" && detail.trim()) {
                return detail.trim();
            }
            if (detail && typeof detail === "object") {
                try {
                    return JSON.stringify(detail);
                } catch (_err) {
                    return "Request failed.";
                }
            }
            return "";
        },
        async request(method, url, payload = null) {
            const options = {
                method,
                credentials: "same-origin",
                headers: {},
            };
            if (payload !== null) {
                options.headers["Content-Type"] = "application/json";
                options.body = JSON.stringify(payload);
            }
            const dp = String(this.desktopParticipationToken || "").trim();
            if (dp) {
                options.headers["X-Desktop-Participation"] = dp;
            }

            const response = await fetch(url, options);
            let data = {};
            try {
                data = await response.json();
            } catch (_err) {
                data = {};
            }
            if (!response.ok) {
                if (response.status === 401) {
                    this.authenticated = false;
                    this.me = null;
                }
                const detail = this.extractErrorDetail(data);
                throw new Error(detail || `Request failed (${response.status})`);
            }
            return data;
        },
        async bootstrap() {
            this.booting = true;
            this.clearNotices();
            try {
                const session = await this.request("GET", "/webapi/session");
                this.authenticated = Boolean(session.authenticated);
                this.me = session.me || null;
                this.resetPreloadState();
                this.view = this.pathToView(window.location.pathname);
                if (this.view === "admin" && !this.isAdmin) this.view = "dashboard";
                if (this.view === "profile") {
                    this.profileTargetUserId = this.getProfileTargetUserIdFromLocation();
                    if (Number(this.me?.id || 0) === this.profileTargetUserId) {
                        this.profileTargetUserId = 0;
                    }
                } else {
                    this.profileTargetUserId = 0;
                }
                if (this.authenticated) {
                    await this.loadForCurrentView();
                }
            } catch (error) {
                this.error = error.message;
            } finally {
                this.booting = false;
            }
        },
        async setView(view, fromPopState = false, options = {}) {
            const { profileUserId = null } = options;
            if (this.testParticipationActive) {
                if (!fromPopState) {
                    this.error = "Finish or submit your in-progress test before switching views.";
                }
                return;
            }
            if (view === "admin" && !this.isAdmin) {
                this.error = "Admin access required.";
                return;
            }
            if (view === "profile") {
                if (fromPopState) {
                    this.profileTargetUserId = this.getProfileTargetUserIdFromLocation();
                } else if (profileUserId !== null) {
                    const targetUserId = Number(profileUserId);
                    this.profileTargetUserId = Number.isInteger(targetUserId) && targetUserId > 0 ? targetUserId : 0;
                } else {
                    this.profileTargetUserId = 0;
                }
                if (Number(this.me?.id || 0) === this.profileTargetUserId) {
                    this.profileTargetUserId = 0;
                }
            } else {
                this.profileTargetUserId = 0;
            }
            this.view = view;
            if (!fromPopState) {
                window.history.pushState({}, "", this.viewToPath(view));
            }
            await this.loadForCurrentView();
        },
        async loadForCurrentView() {
            if (!this.authenticated) return;
            const targetProfileUserId = Number(this.profileTargetUserId || 0);
            if (this.view === "profile" && targetProfileUserId > 0 && targetProfileUserId !== Number(this.me?.id || 0)) {
                await this.loadPublicProfile(targetProfileUserId);
                this.preloadInactiveViews();
                return;
            }
            const activeView =
                this.view === "profile" ? "profile" : this.view === "admin" && this.isAdmin ? "admin" : "dashboard";

            if (!this.preloadStatus[activeView]) {
                await this.loadViewData(activeView);
            } else if (this.isViewDataStale(activeView)) {
                this.preloadViewData(activeView, { force: true }).catch(() => {});
            }

            this.preloadInactiveViews();
        },
        async loginSubmit() {
            this.clearNotices();
            if (!this.login.username || !this.login.password) {
                this.error = "Please enter username/email and password.";
                return;
            }
            this.busy = true;
            try {
                const data = await this.request("POST", "/webapi/login", this.login);
                this.authenticated = true;
                this.me = data.me;
                this.login.password = "";
                this.success = "Welcome back.";
                this.resetPreloadState();
                if (this.view === "admin" && !this.isAdmin) this.view = "dashboard";
                if (this.view !== "profile") {
                    this.profileTargetUserId = 0;
                }
                window.history.replaceState({}, "", this.viewToPath(this.view));
                await this.loadForCurrentView();
            } catch (error) {
                this.error = error.message;
            } finally {
                this.busy = false;
            }
        },
        async logout() {
            if (this.testParticipationActive) {
                this.error = "Submit your in-progress test before logging out.";
                return;
            }
            this.clearNotices();
            try {
                await this.request("POST", "/webapi/logout", {});
            } catch (_err) {
                // ignore logout transport errors
            }
            this.authenticated = false;
            this.me = null;
            this.view = "dashboard";
            this.profileTargetUserId = 0;
            this.profileIsPublic = false;
            this.profilePublicRole = "";
            this.dashboard.social_dashboard.tests = [];
            this.testSearchQuery = "";
            this.clearDashboardTestFilters();
            this.commentSectionExpanded = {};
            this.resetPreloadState();
            window.history.replaceState({}, "", "/");
        },
        async loadDashboard(options = {}) {
            const { silent = false } = options;
            if (!silent) {
                this.clearNotices();
                this.busy = true;
            }
            try {
                const data = await this.request("GET", "/webapi/dashboard");
                const normalized = this.normalizeDashboardPayload(data);
                this.dashboard = normalized;
                if (this.me?.id !== undefined && normalized.profile?.user) {
                    const credits = normalized.profile.user.credits;
                    if (Number.isFinite(Number(credits))) {
                        this.me.credits = Number(credits);
                    }
                    if (normalized.profile.user.role) {
                        this.me.role = normalized.profile.user.role;
                    }
                }
                const activeTestIds = new Set(normalized.social_dashboard.tests.map((item) => String(item.id)));
                for (const testId of Object.keys(this.commentVisibleCounts)) {
                    if (!activeTestIds.has(testId)) {
                        delete this.commentVisibleCounts[testId];
                    }
                }
                for (const testId of Object.keys(this.commentSectionExpanded)) {
                    if (!activeTestIds.has(testId)) {
                        delete this.commentSectionExpanded[testId];
                    }
                }
                for (const test of normalized.social_dashboard.tests) {
                    if (!Object.prototype.hasOwnProperty.call(this.commentDrafts, test.id)) {
                        this.commentDrafts[test.id] = "";
                    }
                    if (!Object.prototype.hasOwnProperty.call(this.commentVisibleCounts, test.id)) {
                        this.commentVisibleCounts[test.id] = 2;
                    }
                    this.commentVisibleCounts[test.id] = Math.max(2, this.commentVisibleCounts[test.id]);
                }
                this.markViewDataFresh("dashboard");
            } catch (error) {
                this.preloadStatus.dashboard = false;
                this.preloadFetchedAt.dashboard = 0;
                if (!silent) {
                    this.error = error.message;
                }
            } finally {
                if (!silent) {
                    this.busy = false;
                }
            }
        },
        async loadProfile(options = {}) {
            const { silent = false } = options;
            if (!silent) {
                this.clearNotices();
                this.busy = true;
            }
            try {
                this.profileLoading = true;
                this.profile = await this.request("GET", "/webapi/profile");
                this.profileIsPublic = false;
                this.profilePublicRole = "";
                this.profileTargetUserId = 0;
                this.markViewDataFresh("profile");
            } catch (error) {
                this.preloadStatus.profile = false;
                this.preloadFetchedAt.profile = 0;
                if (!silent) {
                    this.error = error.message;
                }
            } finally {
                this.profileLoading = false;
                if (!silent) {
                    this.busy = false;
                }
            }
        },
        async loadPublicProfile(userId, options = {}) {
            const { silent = false } = options;
            if (!silent) {
                this.clearNotices();
                this.busy = true;
            }
            this.profileLoading = true;
            this.profileIsPublic = true;
            this.profilePublicRole = "";
            this.profileTargetUserId = Number(userId || 0);
            this.profile = this.emptyProfilePayload(userId);
            try {
                const data = await this.request("GET", `/webapi/community/users/${userId}/profile`);
                this.profile = {
                    profile: {
                        user: {
                            id: Number(data.user?.id || userId),
                            username: String(data.user?.username || ""),
                            email: "",
                            credits: 0,
                        },
                        tests_done: Number(data.tests_done || 0),
                        passed_tests: Number(data.passed_tests || 0),
                        failed_tests: Number(data.failed_tests || 0),
                        success_rate_percent: Number(data.success_rate_percent || 0),
                    },
                    my_results: Array.isArray(data.recent_results) ? data.recent_results : [],
                };
                this.profileIsPublic = true;
                this.profilePublicRole = String(data.user?.role || "");
                this.profileTargetUserId = Number(data.user?.id || userId);
            } catch (error) {
                if (!silent) {
                    this.error = error.message;
                }
            } finally {
                this.profileLoading = false;
                if (!silent) {
                    this.busy = false;
                }
            }
        },
        async postComment(testConfigId) {
            const content = (this.commentDrafts[testConfigId] || "").trim();
            if (!content) {
                this.error = "Comment cannot be empty.";
                return;
            }
            this.clearNotices();
            this.busy = true;
            try {
                await this.request("POST", `/webapi/community/comments/${testConfigId}`, { content });
                this.commentDrafts[testConfigId] = "";
                this.success = "Comment posted.";
                await this.loadDashboard();
                this.commentSectionExpanded[String(testConfigId)] = true;
            } catch (error) {
                this.error = error.message;
            } finally {
                this.busy = false;
            }
        },
        async toggleFollow(userId, currentlyFollowing) {
            this.clearNotices();
            this.busy = true;
            try {
                if (currentlyFollowing) {
                    await this.request("DELETE", `/webapi/community/follow/${userId}`);
                    this.success = "User unfollowed.";
                } else {
                    await this.request("POST", `/webapi/community/follow/${userId}`);
                    this.success = "Now following user.";
                }
                await this.loadDashboard();
            } catch (error) {
                this.error = error.message;
            } finally {
                this.busy = false;
            }
        },
        async loadAdmin(options = {}) {
            const { silent = false } = options;
            if (!silent) {
                this.clearNotices();
                this.busy = true;
            }
            try {
                const data = await this.request("GET", "/webapi/admin/overview");
                this.admin.users = data.users || [];
                this.admin.sections = (data.sections || []).map((section) => this.normalizeAdminSection(section));
                this.admin.questions = data.questions || [];
                this.admin.test_configs = (data.test_configs || []).map((item) => ({
                    ...item,
                    duration_minutes: Math.max(1, Math.floor(Number(item.duration_seconds || 0) / 60)),
                }));
                if (!["tests", "users", "stats"].includes(this.admin.activeTab)) {
                    this.admin.activeTab = "tests";
                }
                const availableConfigIds = new Set(this.admin.test_configs.map((item) => item.id));
                if (!availableConfigIds.has(Number(this.admin.selectedTestConfigId))) {
                    this.admin.selectedTestConfigId = this.admin.test_configs.length ? this.admin.test_configs[0].id : 0;
                }
                const availableQuestionConfigIds = new Set(this.admin.test_configs.map((item) => item.id));
                if (!availableQuestionConfigIds.has(Number(this.admin.questionForm.test_config_id))) {
                    this.admin.questionForm.test_config_id = this.admin.test_configs.length ? this.admin.test_configs[0].id : 0;
                }
                if (!this.admin.sectionForm.test_config_id || !availableQuestionConfigIds.has(Number(this.admin.sectionForm.test_config_id))) {
                    this.admin.sectionForm.test_config_id = this.admin.selectedTestConfigId || (this.admin.test_configs.length ? this.admin.test_configs[0].id : 0);
                }
                if (this.admin.testFormMode === "update") {
                    const fresh = this.admin.test_configs.find((item) => item.id === this.admin.testForm.id);
                    if (fresh) {
                        this.prepareEditTest(fresh);
                    } else {
                        this.admin.testFormMode = "create";
                        this.resetAdminTestForm();
                    }
                }
                const availableUserIds = new Set(this.admin.users.map((item) => item.id));
                if (!availableUserIds.has(Number(this.admin.selectedUserId))) {
                    this.admin.selectedUserId = this.admin.users.length ? this.admin.users[0].id : 0;
                    this.admin.selectedUserStats = null;
                    this.admin.selectedUserStatsFetchedAt = 0;
                }
                this.markViewDataFresh("admin");
                if (this.admin.selectedUserId && this.isSelectedUserStatsStale(this.admin.selectedUserId)) {
                    this.preloadSelectedUserStats();
                }
            } catch (error) {
                this.preloadStatus.admin = false;
                this.preloadFetchedAt.admin = 0;
                if (!silent) {
                    this.error = error.message;
                }
            } finally {
                if (!silent) {
                    this.busy = false;
                }
            }
        },
        async createUser() {
            this.clearNotices();
            const form = this.admin.createUser;
            const username = String(form.username || "").trim();
            const email = String(form.email || "").trim();
            const password = String(form.password || "");
            const role = this.me?.role === "super_admin" && form.role === "admin" ? "admin" : "user";
            const creditsInput = form.credits === "" || form.credits === null || typeof form.credits === "undefined" ? 0 : form.credits;
            const credits = Number(creditsInput);

            if (!username || !email || !password) {
                this.error = "Username, email and password are required.";
                return;
            }
            if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
                this.error = "Enter a valid email address.";
                return;
            }
            if (password.length < 8) {
                this.error = "Password must be at least 8 characters.";
                return;
            }
            if (!Number.isInteger(credits) || credits < 0) {
                this.error = "Starting credits must be a whole number greater than or equal to 0.";
                return;
            }
            this.busy = true;
            try {
                await this.request("POST", "/webapi/admin/users", {
                    username,
                    email,
                    password,
                    role,
                    credits,
                });
                this.success = "User created successfully.";
                this.admin.createUser = {
                    username: "",
                    email: "",
                    password: "",
                    role: "user",
                    credits: 0,
                };
                await this.loadAdmin();
                this.closeUserModal();
            } catch (error) {
                this.error = error.message;
            } finally {
                this.busy = false;
            }
        },
        applySelectedUserStats(data) {
            this.admin.selectedUserStats = data;
            this.admin.selectedUserStatsFetchedAt = Date.now();
            this.admin.editUser = {
                username: data.user.username,
                email: data.user.email,
                role: data.user.role,
                credits: data.user.credits,
                is_active: data.user.is_active,
                password: "",
                credits_to_add: 1,
            };
        },
        isSelectedUserStatsStale(userId) {
            const targetUserId = Number(userId || this.admin.selectedUserId);
            if (!targetUserId) return true;
            const loadedUserId = Number(this.admin.selectedUserStats?.user?.id || 0);
            if (loadedUserId !== targetUserId) return true;
            const fetchedAt = Number(this.admin.selectedUserStatsFetchedAt || 0);
            if (!fetchedAt) return true;
            return Date.now() - fetchedAt > this.preloadTtlMs;
        },
        async preloadSelectedUserStats() {
            const targetUserId = Number(this.admin.selectedUserId);
            if (!targetUserId) return;
            if (!this.isSelectedUserStatsStale(targetUserId)) return;
            try {
                const data = await this.request("GET", `/webapi/admin/users/${targetUserId}/stats`);
                if (Number(this.admin.selectedUserId) === targetUserId) {
                    this.applySelectedUserStats(data);
                }
            } catch (_error) {
                // Ignore preload errors and keep explicit edit flow as fallback.
            }
        },
        async selectUser(options = {}) {
            const { force = false } = options;
            if (!this.admin.selectedUserId) {
                this.admin.selectedUserStats = null;
                this.admin.selectedUserStatsFetchedAt = 0;
                return;
            }
            if (!force && !this.isSelectedUserStatsStale(this.admin.selectedUserId)) {
                return;
            }
            this.clearNotices();
            this.busy = true;
            try {
                const data = await this.request("GET", `/webapi/admin/users/${this.admin.selectedUserId}/stats`);
                this.applySelectedUserStats(data);
            } catch (error) {
                this.error = error.message;
            } finally {
                this.busy = false;
            }
        },
        async saveUser() {
            if (!this.admin.selectedUserId || !this.admin.selectedUserStats) return;
            this.clearNotices();
            this.busy = true;
            try {
                const payload = { ...this.admin.editUser };
                delete payload.credits_to_add;
                if (this.admin.selectedUserStats.user.role === "super_admin") {
                    delete payload.role;
                }
                if (!payload.password) delete payload.password;
                await this.request("PATCH", `/webapi/admin/users/${this.admin.selectedUserId}`, payload);
                this.success = "User updated.";
                await this.loadAdmin();
                this.closeUserModal();
            } catch (error) {
                this.error = error.message;
            } finally {
                this.busy = false;
            }
        },
        async addCredits() {
            if (!this.admin.selectedUserId || !this.admin.editUser.credits_to_add) return;
            this.clearNotices();
            this.busy = true;
            try {
                await this.request("PATCH", `/webapi/admin/users/${this.admin.selectedUserId}/credits`, {
                    credits_to_add: Number(this.admin.editUser.credits_to_add),
                });
                this.success = "Credits added.";
                await this.loadAdmin();
                await this.selectUser({ force: true });
            } catch (error) {
                this.error = error.message;
            } finally {
                this.busy = false;
            }
        },
    },
    async mounted() {
        this.installParticipationAntiCheat();
        window.addEventListener("popstate", async () => {
            const target = this.pathToView(window.location.pathname);
            await this.setView(target, true);
        });
        await this.bootstrap();
    },
}).mount("#app");
