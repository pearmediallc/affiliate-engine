import axios from 'axios';

const PROD_HOST = 'https://affiliate-engine-pl4p.onrender.com';
const LOCAL_HOST = 'http://localhost:8000';

function detectHost() {
  if (typeof window !== 'undefined' && window.location.hostname !== 'localhost') {
    return PROD_HOST;
  }
  return LOCAL_HOST;
}

export const API_HOST = process.env.NEXT_PUBLIC_API_HOST || detectHost();
const API_URL = process.env.NEXT_PUBLIC_API_URL || `${API_HOST}/api/v1`;
export const API_BASE_URL = API_URL;
const CLIENT_ID = 'demo-client';

const apiClient = axios.create({
  baseURL: API_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Attach auth token from localStorage on every request
apiClient.interceptors.request.use((config) => {
  if (typeof window !== 'undefined') {
    const token = localStorage.getItem('auth_token');
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
  }
  return config;
});

// Templates
export const fetchTemplates = async (vertical = 'home_insurance') => {
  const response = await apiClient.get(`/templates/vertical/${vertical}`);
  return response.data;
};

// Images
export const generateImages = async (
  templateId: string,
  context?: string,
  count = 5,
  useAffiliateAngles = true,
  affiliateAngle = 'benefit',
  useGemmaVariations = false,
  referenceImageBase64?: string,
  referenceText?: string,
  vertical: string = 'home_insurance',
  style: string = 'professional_photography',
  textMode: string = 'none',
  postProcess: string = 'editorial',
  headlineText?: string,
  subheadingText?: string,
  ctaText?: string,
  cinemaCamera?: string,
  cinemaLens?: string,
  cinemaFocalLength?: string,
  cinemaAperture?: string,
) => {
  const response = await apiClient.post(`/images/generate?client_id=${CLIENT_ID}`, {
    vertical: vertical,
    template_id: templateId || undefined,
    count,
    additional_context: context,
    use_affiliate_angles: useAffiliateAngles,
    affiliate_angle: affiliateAngle,
    use_gemma_variations: useGemmaVariations,
    reference_text: referenceText || context,
    reference_image_base64: referenceImageBase64,
    style: style,
    text_mode: textMode,
    post_process: postProcess,
    headline_text: headlineText || undefined,
    subheading_text: subheadingText || undefined,
    cta_text: ctaText || undefined,
    cinema_camera: cinemaCamera || undefined,
    cinema_lens: cinemaLens || undefined,
    cinema_focal_length: cinemaFocalLength || undefined,
    cinema_aperture: cinemaAperture || undefined,
  });
  return response.data;
};

export const fetchImages = async (page = 1, pageSize = 10) => {
  const response = await apiClient.get(
    `/images/list?client_id=${CLIENT_ID}&vertical=home_insurance&page=${page}&page_size=${pageSize}`
  );
  return response.data;
};

// Analytics
export const fetchAnalytics = async () => {
  const response = await apiClient.get(`/analytics/overview?client_id=${CLIENT_ID}`);
  return response.data.data;
};

export const fetchVerticalAnalytics = async (vertical = 'home_insurance') => {
  const response = await apiClient.get(
    `/analytics/vertical/${vertical}?client_id=${CLIENT_ID}`
  );
  return response.data.data;
};

export const fetchTopTemplates = async (limit = 5) => {
  const response = await apiClient.get(
    `/analytics/top-templates?client_id=${CLIENT_ID}&limit=${limit}`
  );
  return response.data.data;
};

export const fetchBilling = async () => {
  const response = await apiClient.get(`/analytics/billing?client_id=${CLIENT_ID}`);
  return response.data.data;
};

export const fetchTimeSeries = async (days = 30) => {
  const response = await apiClient.get(
    `/analytics/time-series?client_id=${CLIENT_ID}&days=${days}`
  );
  return response.data.data;
};

// Download image
export const downloadImage = async (imageId: string) => {
  try {
    const response = await fetch(`${API_URL}/images/download/${imageId}`);
    if (!response.ok) {
      throw new Error(`Download failed: ${response.statusText}`);
    }

    const blob = await response.blob();
    const url = window.URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `affiliate-image-${imageId.substring(0, 12)}.png`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    window.URL.revokeObjectURL(url);

    return true;
  } catch (error) {
    console.error('Download error:', error);
    throw error;
  }
};

// Speech Generation
export const generateSpeech = async (params: {
  text: string;
  voice?: string;
  style?: string;
  language?: string;
  output_format?: string;
}) => {
  const response = await apiClient.post('/speech/generate', {
    text: params.text,
    voice: params.voice || 'Kore',
    style: params.style,
    language: params.language || 'en',
    output_format: params.output_format || 'mp3',
  });
  return response.data;
};

export const getSpeechVoices = async () => {
  const response = await apiClient.get('/speech/voices');
  return response.data;
};

export const getSpeechLanguages = async () => {
  const response = await apiClient.get('/speech/languages');
  return response.data;
};

// Script Generation
export const generateScript = async (params: {
  product: string;
  vertical: string;
  target_audience: string;
  framework?: string;
  angle?: string;
  psychological_triggers?: string[];
  include_cta?: boolean;
}) => {
  const response = await apiClient.post('/scripts/generate', {
    product: params.product,
    vertical: params.vertical || 'home_insurance',
    target_audience: params.target_audience,
    framework: params.framework || 'PAS',
    angle: params.angle || 'benefit',
    psychological_triggers: params.psychological_triggers,
    include_cta: params.include_cta ?? true,
  });
  return response.data;
};

export const iterateScript = async (params: {
  original_script: string;
  feedback: string;
  preserve_elements?: string[];
}) => {
  const response = await apiClient.post('/scripts/iterate', {
    original_script: params.original_script,
    feedback: params.feedback,
    preserve_elements: params.preserve_elements,
  });
  return response.data;
};

export const getScriptFrameworks = async () => {
  const response = await apiClient.get('/scripts/frameworks');
  return response.data;
};

export const getScriptTriggers = async () => {
  const response = await apiClient.get('/scripts/triggers');
  return response.data;
};

// Template Analysis
export const analyzeImage = async (imageBase64: string) => {
  const response = await apiClient.post('/templates/analyze', {
    image_base64: imageBase64,
  });
  return response.data;
};

export const extractTemplate = async (imagesBase64: string[]) => {
  const response = await apiClient.post('/templates/extract', {
    images_base64: imagesBase64,
  });
  return response.data;
};

// ─────────────────────────────────────── Campaign pipeline API

function authHeaders() {
  const token = typeof window !== 'undefined' ? localStorage.getItem('auth_token') : null;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

// Campaigns
export const createCampaign = async (data: {
  name: string;
  vertical: string;
  brief_text?: string;
  reference_video?: File | null;
  reference_image?: File | null;
}) => {
  const form = new FormData();
  form.append('name', data.name);
  form.append('vertical', data.vertical);
  if (data.brief_text) form.append('brief_text', data.brief_text);
  if (data.reference_video) form.append('reference_video', data.reference_video);
  if (data.reference_image) form.append('reference_image', data.reference_image);
  const response = await axios.post(`${API_URL}/campaigns`, form, {
    headers: { ...authHeaders() },
  });
  return response.data;
};

export const listCampaigns = async () => {
  const r = await apiClient.get('/campaigns');
  return r.data;
};

export const getCampaign = async (id: string) => {
  const r = await apiClient.get(`/campaigns/${id}`);
  return r.data;
};

export const runBriefing = async (id: string) => {
  const r = await apiClient.post(`/campaigns/${id}/brief`);
  return r.data;
};

export const runScripting = async (id: string, target_duration = 30, extra_instructions = '') => {
  const r = await apiClient.post(`/campaigns/${id}/script`, { target_duration, extra_instructions });
  return r.data;
};

export const runStoryboarding = async (id: string, character_ids: string[], setting_ids: string[], target_duration = 30) => {
  const r = await apiClient.post(`/campaigns/${id}/storyboard`, { character_ids, setting_ids, target_duration });
  return r.data;
};

export const startGeneration = async (id: string) => {
  const r = await apiClient.post(`/campaigns/${id}/generate`);
  return r.data;
};

export const runEditing = async (id: string, color_grade = 'cinematic', music_mood = 'motivational') => {
  const r = await apiClient.post(`/campaigns/${id}/edit`, { color_grade, music_mood });
  return r.data;
};

export const getCampaignCost = async (id: string) => {
  const r = await apiClient.get(`/campaigns/${id}/cost`);
  return r.data;
};

// Characters
export const createCharacter = async (data: { name: string; description?: string; portrait?: File | null }) => {
  const form = new FormData();
  form.append('name', data.name);
  if (data.description) form.append('description', data.description);
  if (data.portrait) form.append('portrait', data.portrait);
  const r = await axios.post(`${API_URL}/characters`, form, { headers: { ...authHeaders() } });
  return r.data;
};

export const listCharacters = async () => {
  const r = await apiClient.get('/characters');
  return r.data;
};

// Scene settings
export const createSceneSetting = async (data: { name: string; description?: string; location_type?: string; reference_image?: File | null }) => {
  const form = new FormData();
  form.append('name', data.name);
  if (data.description) form.append('description', data.description);
  if (data.location_type) form.append('location_type', data.location_type);
  if (data.reference_image) form.append('reference_image', data.reference_image);
  const r = await axios.post(`${API_URL}/scene-settings`, form, { headers: { ...authHeaders() } });
  return r.data;
};

export const listSceneSettings = async () => {
  const r = await apiClient.get('/scene-settings');
  return r.data;
};

// Variations
export const planVariants = async (campaignId: string, strategies: string[], num_per_strategy = 3) => {
  const r = await apiClient.post(`/variations/${campaignId}/plan`, { strategies, num_per_strategy });
  return r.data;
};

export const createVariation = async (campaignId: string, data: {
  strategy: string;
  label?: string;
  new_character_id?: string;
  new_setting_id?: string;
  style_model?: string;
  auto_generate?: boolean;
}) => {
  const r = await apiClient.post(`/variations/${campaignId}/create`, { auto_generate: true, ...data });
  return r.data;
};

export const listVariations = async (campaignId: string) => {
  const r = await apiClient.get(`/variations/${campaignId}/list`);
  return r.data;
};

export const reviewVariation = async (campaignId: string, variationId: string, action: 'approve' | 'reject') => {
  const r = await apiClient.post(`/variations/${campaignId}/${variationId}/review`, { action });
  return r.data;
};

export const editVariation = async (campaignId: string, variationId: string, color_grade = 'cinematic', music_mood = 'motivational') => {
  const r = await apiClient.post(`/variations/${campaignId}/${variationId}/edit`, { color_grade, music_mood });
  return r.data;
};

// Music
export const searchMusic = async (mood = 'motivational', duration_max = 120) => {
  const r = await apiClient.get('/music/search', { params: { mood, duration_max } });
  return r.data;
};

// Stock footage
export const searchStock = async (query: string, orientation = 'portrait') => {
  const r = await apiClient.get('/stock/search', { params: { query, orientation } });
  return r.data;
};

// ─────────────────────────────────────── Harness Engine API

export const optimizePrompt = async (params: {
  raw_prompt: string;
  feature: 'image' | 'video' | 'speech' | 'caption';
  vertical?: string;
  params?: Record<string, unknown>;
}) => {
  const r = await apiClient.post('/harness/optimize', {
    raw_prompt: params.raw_prompt,
    feature: params.feature,
    vertical: params.vertical || 'home_insurance',
    params: params.params || {},
  });
  return r.data;
};

export const recordOutcome = async (params: {
  event_id: string;
  outcome: 'downloaded' | 'rejected' | 'regenerated' | 'approved';
  time_to_action_sec?: number;
  cost_usd?: number;
}) => {
  const r = await apiClient.post('/harness/outcome', params);
  return r.data;
};

export const getHarnessProfile = async (vertical = 'home_insurance') => {
  const r = await apiClient.get(`/harness/profile/${vertical}`);
  return r.data;
};

// Auto-caption: transcribe with Whisper + burn timed captions
export const autoCaptionVideo = async (formData: FormData) => {
  const r = await apiClient.post('/video-edit/auto-caption', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 300000,
  });
  return r.data;
};

// Standalone video editor
export const editVideo = async (formData: FormData) => {
  const r = await apiClient.post('/video-edit/edit', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 300000, // 5 min — ffmpeg can take a while
  });
  return r.data;
};

export default apiClient;
