/**
 * API调用封装 - Flask版本
 * 替代原有的QWebChannel通信方式
 * 
 * 使用方式：
 * - 原来：window.pybridge.extractKnowledgePoints(text, callback)
 * - 现在：await KnowledgeAPI.extract(text)
 */

class API {
    constructor(baseURL = '') {
        this.baseURL = baseURL;
        this.defaultHeaders = {
            'Content-Type': 'application/json',
        };
    }

    /**
     * 通用请求方法
     */
    async request(url, options = {}) {
        const finalOptions = {
            headers: this.defaultHeaders,
            credentials: 'same-origin', // 携带cookie
            ...options,
        };

        try {
            console.log(`[API] ${options.method || 'GET'} ${url}`);
            const response = await fetch(this.baseURL + url, finalOptions);
            const data = await response.json();

            if (!response.ok) {
                throw new Error(data.error || `HTTP ${response.status}`);
            }

            if (!data.success) {
                throw new Error(data.error || '请求失败');
            }

            return data.data; // 直接返回data字段
        } catch (error) {
            console.error(`[API错误] ${url}:`, error);
            throw error;
        }
    }

    async get(url, params = {}) {
        const queryString = new URLSearchParams(params).toString();
        const fullURL = queryString ? `${url}?${queryString}` : url;
        return this.request(fullURL, { method: 'GET' });
    }

    async post(url, data = {}) {
        return this.request(url, {
            method: 'POST',
            body: JSON.stringify(data),
        });
    }

    async put(url, data = {}) {
        return this.request(url, {
            method: 'PUT',
            body: JSON.stringify(data),
        });
    }

    async delete(url, data = {}) {
        return this.request(url, {
            method: 'DELETE',
            body: JSON.stringify(data),
        });
    }
}

// 创建全局API实例
const api = new API();

// ==================== 知识管理API ====================

const KnowledgeAPI = {
    /**
     * 提取知识点
     * @param {string} text - 要提取的文本
     * @returns {Promise<Object>} 提取结果
     */
    async extract(text) {
        return api.post('/api/knowledge/extract', { text });
    },

    /**
     * 获取知识点列表
     * @param {string} subject - 学科名称
     * @returns {Promise<Array>} 知识点列表
     */
    async list(subject) {
        return api.get('/api/knowledge/list', { subject });
    },

    /**
     * 创建知识点
     */
    async create(subject, pointName, description) {
        return api.post('/api/knowledge/create', {
            subject,
            point_name: pointName,
            description
        });
    },

    /**
     * 更新知识点
     */
    async update(id, data) {
        return api.put('/api/knowledge/update', { id, ...data });
    },

    /**
     * 删除知识点
     */
    async delete(id) {
        return api.delete('/api/knowledge/delete', { id });
    }
};

// ==================== 练习管理API ====================

const PracticeAPI = {
    /**
     * 生成练习
     */
    async generate(knowledgePointId, options = {}) {
        return api.post('/api/practice/generate', { 
            knowledge_point_id: knowledgePointId,
            ...options
        });
    },

    /**
     * 评估练习
     */
    async evaluate(practiceId, answer) {
        return api.post('/api/practice/evaluate', {
            practice_id: practiceId,
            answer
        });
    },

    /**
     * 获取练习历史
     */
    async getHistory(limit = 10) {
        return api.get('/api/practice/history', { limit });
    },

    /**
     * 获取练习详情
     */
    async getDetail(practiceId) {
        return api.get('/api/practice/detail', { id: practiceId });
    },

    /**
     * 保存练习
     */
    async save(practiceData) {
        return api.post('/api/practice/save', practiceData);
    }
};

// ==================== LLM调用API ====================

const LLMAPI = {
    /**
     * 调用LLM
     * @param {string} prompt - 提示词
     * @param {string} provider - LLM提供商（可选）
     * @returns {Promise<string>} LLM响应
     */
    async call(prompt, provider = null) {
        return api.post('/api/llm/call', { prompt, provider });
    },

    /**
     * 获取调用日志
     */
    async getLogs(limit = 50) {
        return api.get('/api/llm/logs', { limit });
    },

    /**
     * 获取统计信息
     */
    async getStats() {
        return api.get('/api/llm/stats');
    },

    /**
     * 测试连接
     */
    async test(provider) {
        return api.post('/api/llm/test', { provider });
    }
};

// ==================== 文件操作API ====================

const FileAPI = {
    /**
     * 保存文件
     * @param {string} path - 文件路径（相对于data目录）
     * @param {string} content - 文件内容
     */
    async save(path, content) {
        return api.post('/api/file/save', { path, content });
    },

    /**
     * 加载文件
     * @param {string} path - 文件路径
     * @returns {Promise<string>} 文件内容
     */
    async load(path) {
        return api.get('/api/file/load', { path });
    },

    /**
     * 列出文件
     * @param {string} directory - 目录路径
     * @returns {Promise<Array>} 文件列表
     */
    async list(directory) {
        return api.get('/api/file/list', { directory });
    },

    /**
     * 删除文件
     */
    async delete(path) {
        return api.delete('/api/file/delete', { path });
    },

    /**
     * 上传文件
     * @param {File} file - 文件对象
     * @param {string} directory - 目标目录
     */
    async upload(file, directory = '') {
        const formData = new FormData();
        formData.append('file', file);
        formData.append('directory', directory);

        const response = await fetch('/api/file/upload', {
            method: 'POST',
            body: formData,
            credentials: 'same-origin'
        });

        const data = await response.json();
        if (!data.success) {
            throw new Error(data.error || '上传失败');
        }

        return data.data;
    }
};

// ==================== 笔记管理API ====================

const NoteAPI = {
    /**
     * 保存笔记
     */
    async save(noteData) {
        return api.post('/api/notes/save', noteData);
    },

    /**
     * 加载笔记
     */
    async load(noteId) {
        return api.get('/api/notes/load', { id: noteId });
    },

    /**
     * 获取笔记列表
     */
    async list(filters = {}) {
        return api.get('/api/notes/list', filters);
    },

    /**
     * 删除笔记
     */
    async delete(noteId) {
        return api.delete('/api/notes/delete', { id: noteId });
    }
};

// ==================== 配置管理API ====================

const ConfigAPI = {
    /**
     * 获取配置
     */
    async get() {
        return api.get('/api/config/get');
    },

    /**
     * 保存配置
     */
    async save(config) {
        return api.post('/api/config/save', config);
    },

    /**
     * 重置配置
     */
    async reset() {
        return api.post('/api/config/reset');
    }
};

// ==================== 兼容层（可选）====================

/**
 * 为了最小化前端改造，提供兼容层模拟pybridge
 * 这样可以减少前端代码的修改量
 */
window.pybridge = {
    // 知识管理
    extractKnowledgePoints: async (text, callback) => {
        try {
            const result = await KnowledgeAPI.extract(text);
            if (callback) callback(JSON.stringify(result));
            return JSON.stringify(result);
        } catch (error) {
            console.error('extractKnowledgePoints error:', error);
            if (callback) callback(JSON.stringify({ error: error.message }));
        }
    },

    getKnowledgePoints: async (subject, callback) => {
        try {
            const result = await KnowledgeAPI.list(subject);
            if (callback) callback(JSON.stringify(result));
            return JSON.stringify(result);
        } catch (error) {
            console.error('getKnowledgePoints error:', error);
            if (callback) callback(JSON.stringify({ error: error.message }));
        }
    },

    // LLM调用
    callLLM: async (prompt, provider, callback) => {
        try {
            const result = await LLMAPI.call(prompt, provider);
            if (callback) callback(result);
            return result;
        } catch (error) {
            console.error('callLLM error:', error);
            if (callback) callback(JSON.stringify({ error: error.message }));
        }
    },

    // 文件操作
    saveFile: async (path, content, callback) => {
        try {
            const result = await FileAPI.save(path, content);
            if (callback) callback(JSON.stringify(result));
            return JSON.stringify(result);
        } catch (error) {
            console.error('saveFile error:', error);
            if (callback) callback(JSON.stringify({ error: error.message }));
        }
    },

    loadFile: async (path, callback) => {
        try {
            const result = await FileAPI.load(path);
            if (callback) callback(result);
            return result;
        } catch (error) {
            console.error('loadFile error:', error);
            if (callback) callback('');
        }
    },

    // 配置管理
    getConfig: async (callback) => {
        try {
            const result = await ConfigAPI.get();
            if (callback) callback(JSON.stringify(result));
            return JSON.stringify(result);
        } catch (error) {
            console.error('getConfig error:', error);
            if (callback) callback(JSON.stringify({}));
        }
    },

    saveConfig: async (config, callback) => {
        try {
            const result = await ConfigAPI.save(JSON.parse(config));
            if (callback) callback(JSON.stringify(result));
            return JSON.stringify(result);
        } catch (error) {
            console.error('saveConfig error:', error);
            if (callback) callback(JSON.stringify({ error: error.message }));
        }
    }
};

console.log('✅ Flask API封装加载完成');
console.log('可用的API模块：', {
    KnowledgeAPI,
    PracticeAPI,
    LLMAPI,
    FileAPI,
    NoteAPI,
    ConfigAPI
});
