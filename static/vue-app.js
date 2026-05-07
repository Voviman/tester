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
            commentDrafts: {},
            commentVisibleCounts: {},
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
                activeTab: "tests",
                testSearchQuery: "",
                userSearchQuery: "",
                selectedTestConfigId: 0,
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
                testFormMode: "create",
                userFormMode: "create",
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
                    question_text: "",
                    options: ["", "", "", ""],
                    correct_indices: [],
                },
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
            if (!query) return users;
            return users.filter((user) => String(user.username || "").toLowerCase().includes(query));
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
        selectAdminTest(testConfigId) {
            this.admin.selectedTestConfigId = Number(testConfigId) || 0;
        },
        async selectAdminUser(userId) {
            this.admin.selectedUserId = Number(userId) || 0;
            if (this.admin.userFormMode === "update") {
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
        },
        async openUpdateUserMode() {
            const target = this.activeAdminUser;
            if (!target) {
                this.error = "No users available to edit.";
                return;
            }
            this.admin.userFormMode = "update";
            await this.selectAdminUser(target.id);
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
        setQuestionTarget(testConfigId) {
            this.admin.questionForm.test_config_id = Number(testConfigId) || 0;
        },
        resetQuestionForm() {
            const keepTestId = Number(this.admin.questionForm.test_config_id) || 0;
            this.admin.questionForm = {
                id: 0,
                test_config_id: keepTestId,
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
                const activeTestIds = new Set(data.social_dashboard.tests.map((item) => String(item.id)));
                for (const testId of Object.keys(this.commentVisibleCounts)) {
                    if (!activeTestIds.has(testId)) {
                        delete this.commentVisibleCounts[testId];
                    }
                }
                for (const test of data.social_dashboard.tests) {
                    if (!Object.prototype.hasOwnProperty.call(this.commentDrafts, test.id)) {
                        this.commentDrafts[test.id] = "";
                    }
                    if (!Object.prototype.hasOwnProperty.call(this.commentVisibleCounts, test.id)) {
                        this.commentVisibleCounts[test.id] = 2;
                    }
                    this.commentVisibleCounts[test.id] = Math.max(2, this.commentVisibleCounts[test.id]);
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
                if (!["tests", "users"].includes(this.admin.activeTab)) {
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
    },
    async mounted() {
        window.addEventListener("popstate", async () => {
            const target = this.pathToView(window.location.pathname);
            await this.setView(target, true);
        });
        await this.bootstrap();
    },
}).mount("#app");
