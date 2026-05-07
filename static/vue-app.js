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
            commentDrafts: {},
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
            admin: {
                users: [],
                test_configs: [],
                questions: [],
                selectedUserId: 0,
                selectedUserStats: null,
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
                builder: {
                    topic_name: "",
                    level_name: "",
                    duration_minutes: 15,
                    passing_percent: 60,
                    question_text: "",
                    options: ["", "", "", ""],
                    correct_index: 0,
                },
            },
        };
    },
    computed: {
        isAdmin() {
            return this.me && (this.me.role === "admin" || this.me.role === "super_admin");
        },
    },
    methods: {
        pathToView(pathname) {
            if (pathname === "/profile") return "profile";
            if (pathname === "/admin") return "admin";
            return "dashboard";
        },
        viewToPath(view) {
            if (view === "profile") return "/profile";
            if (view === "admin") return "/admin";
            return "/dashboard";
        },
        clearNotices() {
            this.error = "";
            this.success = "";
        },
        formatDate(value) {
            if (!value) return "-";
            try {
                return new Date(value).toLocaleString();
            } catch (_err) {
                return String(value);
            }
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
                throw new Error(data.detail || `Request failed (${response.status})`);
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
                this.view = this.pathToView(window.location.pathname);
                if (this.view === "admin" && !this.isAdmin) this.view = "dashboard";
                if (this.authenticated) {
                    await this.loadForCurrentView();
                }
            } catch (error) {
                this.error = error.message;
            } finally {
                this.booting = false;
            }
        },
        async setView(view, fromPopState = false) {
            if (view === "admin" && !this.isAdmin) {
                this.error = "Admin access required.";
                return;
            }
            this.view = view;
            if (!fromPopState) {
                window.history.pushState({}, "", this.viewToPath(view));
            }
            await this.loadForCurrentView();
        },
        async loadForCurrentView() {
            if (!this.authenticated) return;
            if (this.view === "profile") {
                await this.loadProfile();
                return;
            }
            if (this.view === "admin" && this.isAdmin) {
                await this.loadAdmin();
                return;
            }
            await this.loadDashboard();
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
                if (this.view === "admin" && !this.isAdmin) this.view = "dashboard";
                window.history.replaceState({}, "", this.viewToPath(this.view));
                await this.loadForCurrentView();
            } catch (error) {
                this.error = error.message;
            } finally {
                this.busy = false;
            }
        },
        async logout() {
            this.clearNotices();
            try {
                await this.request("POST", "/webapi/logout", {});
            } catch (_err) {
                // ignore logout transport errors
            }
            this.authenticated = false;
            this.me = null;
            this.view = "dashboard";
            this.dashboard.social_dashboard.tests = [];
            window.history.replaceState({}, "", "/");
        },
        async loadDashboard() {
            this.clearNotices();
            this.busy = true;
            try {
                const data = await this.request("GET", "/webapi/dashboard");
                this.dashboard = data;
                for (const test of data.social_dashboard.tests) {
                    if (!Object.prototype.hasOwnProperty.call(this.commentDrafts, test.id)) {
                        this.commentDrafts[test.id] = "";
                    }
                }
            } catch (error) {
                this.error = error.message;
            } finally {
                this.busy = false;
            }
        },
        async loadProfile() {
            this.clearNotices();
            this.busy = true;
            try {
                this.profile = await this.request("GET", "/webapi/profile");
            } catch (error) {
                this.error = error.message;
            } finally {
                this.busy = false;
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
        async loadAdmin() {
            this.clearNotices();
            this.busy = true;
            try {
                const data = await this.request("GET", "/webapi/admin/overview");
                this.admin.users = data.users || [];
                this.admin.questions = data.questions || [];
                this.admin.test_configs = (data.test_configs || []).map((item) => ({
                    ...item,
                    duration_minutes: Math.max(1, Math.floor(Number(item.duration_seconds || 0) / 60)),
                }));
                if (
                    this.admin.selectedUserId &&
                    !this.admin.users.some((item) => item.id === this.admin.selectedUserId)
                ) {
                    this.admin.selectedUserId = 0;
                    this.admin.selectedUserStats = null;
                }
            } catch (error) {
                this.error = error.message;
            } finally {
                this.busy = false;
            }
        },
        async createUser() {
            this.clearNotices();
            const form = this.admin.createUser;
            if (!form.username || !form.email || !form.password) {
                this.error = "Username, email and password are required.";
                return;
            }
            this.busy = true;
            try {
                await this.request("POST", "/webapi/admin/users", form);
                this.success = "User created successfully.";
                this.admin.createUser = {
                    username: "",
                    email: "",
                    password: "",
                    role: "user",
                    credits: 0,
                };
                await this.loadAdmin();
            } catch (error) {
                this.error = error.message;
            } finally {
                this.busy = false;
            }
        },
        async selectUser() {
            if (!this.admin.selectedUserId) {
                this.admin.selectedUserStats = null;
                return;
            }
            this.clearNotices();
            this.busy = true;
            try {
                const data = await this.request("GET", `/webapi/admin/users/${this.admin.selectedUserId}/stats`);
                this.admin.selectedUserStats = data;
                this.admin.editUser = {
                    username: data.user.username,
                    email: data.user.email,
                    role: data.user.role,
                    credits: data.user.credits,
                    is_active: data.user.is_active,
                    password: "",
                    credits_to_add: 1,
                };
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
                await this.selectUser();
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
                await this.selectUser();
            } catch (error) {
                this.error = error.message;
            } finally {
                this.busy = false;
            }
        },
        async submitBuilder() {
            this.clearNotices();
            const builder = this.admin.builder;
            if (
                !builder.topic_name ||
                !builder.level_name ||
                !builder.question_text ||
                builder.options.some((item) => !String(item).trim())
            ) {
                this.error = "Fill all test constructor fields.";
                return;
            }
            this.busy = true;
            try {
                await this.request("POST", "/webapi/admin/test-builder", builder);
                this.success = "Test configuration saved and question added.";
                this.admin.builder.question_text = "";
                this.admin.builder.options = ["", "", "", ""];
                this.admin.builder.correct_index = 0;
                await this.loadAdmin();
            } catch (error) {
                this.error = error.message;
            } finally {
                this.busy = false;
            }
        },
        async saveConfig(config) {
            this.clearNotices();
            this.busy = true;
            try {
                await this.request("PATCH", `/webapi/admin/test-configs/${config.id}`, {
                    topic_name: config.topic_name,
                    level_name: config.level_name,
                    duration_minutes: Number(config.duration_minutes),
                    passing_percent: Number(config.passing_percent),
                    is_active: Boolean(config.is_active),
                });
                this.success = `Config #${config.id} updated.`;
                await this.loadAdmin();
            } catch (error) {
                this.error = error.message;
            } finally {
                this.busy = false;
            }
        },
    },
    async mounted() {
        window.addEventListener("popstate", async () => {
            const target = this.pathToView(window.location.pathname);
            await this.setView(target, true);
        });
        await this.bootstrap();
    },
}).mount("#app");
