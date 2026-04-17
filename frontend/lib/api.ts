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
  style: string = 'professional_photography'
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

export default apiClient;
