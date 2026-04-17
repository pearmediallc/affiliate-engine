'use client';

import Image from 'next/image';
import { useState } from 'react';
import { downloadImage, API_BASE_URL, API_HOST } from '@/lib/api';
import axios from 'axios';

const ISSUE_TAGS = [
  'Spelling Errors',
  'Wrong Style',
  'Missing Elements',
  'Wrong Colors',
  'Poor Composition',
  'Not Converting',
];

function getImageSrc(imageUrl: string | null | undefined): string | null {
  if (!imageUrl) return null;
  if (imageUrl.includes('placeholder')) return null;
  // Relative API path like /api/v1/images/serve/xxx.png
  if (imageUrl.startsWith('/api/')) return `${API_HOST}${imageUrl}`;
  // Already a full URL or data URI
  return imageUrl;
}

function FeedbackWidget({ imageId }: { imageId: string }) {
  const [submitted, setSubmitted] = useState(false);
  const [rating, setRating] = useState<'positive' | 'negative' | null>(null);
  const [selectedIssues, setSelectedIssues] = useState<string[]>([]);
  const [comment, setComment] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const toggleIssue = (issue: string) => {
    setSelectedIssues((prev) =>
      prev.includes(issue) ? prev.filter((i) => i !== issue) : [...prev, issue]
    );
  };

  const handleSubmit = async () => {
    if (!rating) return;
    setSubmitting(true);
    try {
      await axios.post(`${API_BASE_URL}/feedback/submit`, {
        image_id: imageId,
        rating,
        issues: selectedIssues,
        comment: comment || undefined,
      });
      setSubmitted(true);
    } catch (err) {
      console.error('Feedback submission failed:', err);
    } finally {
      setSubmitting(false);
    }
  };

  if (submitted) {
    return (
      <div className="mt-3 text-center text-sm text-green-600 font-medium py-2">
        Feedback submitted
      </div>
    );
  }

  return (
    <div className="mt-3 border-t border-gray-200 pt-3" onClick={(e) => e.stopPropagation()}>
      <div className="flex items-center gap-2 mb-2">
        <span className="text-xs text-gray-500">Rate this image:</span>
        <button
          onClick={() => setRating('positive')}
          className={`text-lg leading-none px-1 rounded ${rating === 'positive' ? 'bg-green-100' : 'hover:bg-gray-100'}`}
          title="Good"
        >
          👍
        </button>
        <button
          onClick={() => setRating('negative')}
          className={`text-lg leading-none px-1 rounded ${rating === 'negative' ? 'bg-red-100' : 'hover:bg-gray-100'}`}
          title="Bad"
        >
          👎
        </button>
      </div>

      {rating === 'negative' && (
        <div className="space-y-2">
          <div className="flex flex-wrap gap-1">
            {ISSUE_TAGS.map((issue) => (
              <button
                key={issue}
                onClick={() => toggleIssue(issue)}
                className={`text-xs px-2 py-1 rounded-full border ${
                  selectedIssues.includes(issue)
                    ? 'bg-red-50 border-red-300 text-red-700'
                    : 'border-gray-300 text-gray-600 hover:bg-gray-50'
                }`}
              >
                {issue}
              </button>
            ))}
          </div>
          <textarea
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            placeholder="Optional comment..."
            rows={2}
            className="w-full text-xs border border-gray-300 rounded p-2 resize-none focus:outline-none focus:ring-1 focus:ring-blue-400"
          />
        </div>
      )}

      {rating && (
        <button
          onClick={handleSubmit}
          disabled={submitting}
          className="mt-2 w-full text-xs py-1.5 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
        >
          {submitting ? 'Submitting...' : 'Submit Feedback'}
        </button>
      )}
    </div>
  );
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export default function ImageGallery({ images }: { images: any[] }) {
  const [selectedImage, setSelectedImage] = useState(null);
  const [isDownloading, setIsDownloading] = useState(false);

  const handleDownload = async (image) => {
    try {
      setIsDownloading(true);
      if (!image.id) {
        alert('Image ID not available for download');
        return;
      }

      await downloadImage(image.id);
    } catch (err) {
      console.error('Download failed:', err);
      alert(`Failed to download image: ${err.message}`);
    } finally {
      setIsDownloading(false);
    }
  };

  if (!images || images.length === 0) {
    return (
      <div className="card text-center py-12">
        <p className="text-gray-500 mb-4">No images generated yet</p>
        <p className="text-sm text-gray-400">
          Go to "Generate Images" tab and select a template to get started
        </p>
      </div>
    );
  }

  return (
    <div>
      {/* Image Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6 mb-8">
        {images.map((image) => (
          <div
            key={image.id}
            className="card cursor-pointer hover:shadow-lg transition-shadow"
            onClick={() => setSelectedImage(image)}
          >
            {/* Image Preview */}
            <div className="relative bg-gradient-to-br from-blue-100 to-indigo-200 rounded-lg overflow-hidden mb-4 aspect-video flex items-center justify-center">
              {getImageSrc(image.image_url) ? (
                <img
                  src={getImageSrc(image.image_url)!}
                  alt="Generated"
                  className="w-full h-full object-cover"
                  onError={(e) => {
                    (e.target as HTMLImageElement).style.display = 'none';
                  }}
                />
              ) : (
                <div className="text-center space-y-2">
                  <div className="text-4xl">🎨</div>
                  <p className="text-sm font-medium text-gray-700">Image Generated</p>
                  <p className="text-xs text-gray-500">{image.id.substring(0, 12)}</p>
                </div>
              )}
            </div>

            {/* Image Details */}
            <div className="space-y-2 text-sm">
              <div className="flex justify-between">
                <span className="text-gray-600">Cost:</span>
                <span className="font-medium">${image.cost_usd}</span>
              </div>

              {image.quality_score && (
                <div className="flex justify-between">
                  <span className="text-gray-600">Quality:</span>
                  <span className="font-medium">{image.quality_score}/10</span>
                </div>
              )}

              <div className="pt-2 border-t border-gray-200">
                <p className="text-xs text-gray-500 truncate">
                  ID: {image.id}
                </p>
              </div>
            </div>

            {/* Download Button */}
            <button
              onClick={(e) => {
                e.stopPropagation();
                handleDownload(image);
              }}
              disabled={isDownloading}
              className="mt-4 w-full btn btn-secondary text-sm hover:bg-gray-200 transition disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {isDownloading ? '⏳ Downloading...' : '⬇️ Download'}
            </button>

            {/* Feedback Widget */}
            <FeedbackWidget imageId={image.id} />
          </div>
        ))}
      </div>

      {/* Selected Image Details */}
      {selectedImage && (
        <div className="card">
          <div className="flex justify-between items-start mb-6">
            <h3 className="text-xl font-bold">Image Details</h3>
            <button
              onClick={() => setSelectedImage(null)}
              className="text-gray-400 hover:text-gray-600"
            >
              ✕
            </button>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
            {/* Large Preview */}
            <div className="bg-gradient-to-br from-blue-100 to-indigo-200 rounded-lg overflow-hidden aspect-video flex items-center justify-center">
              {getImageSrc(selectedImage.image_url) ? (
                <img
                  src={getImageSrc(selectedImage.image_url)!}
                  alt="Generated"
                  className="w-full h-full object-cover"
                  onError={(e) => {
                    (e.target as HTMLImageElement).style.display = 'none';
                  }}
                />
              ) : (
                <div className="text-center space-y-3">
                  <div className="text-6xl">🎨</div>
                  <div>
                    <p className="text-lg font-medium text-gray-700">Image Generated</p>
                    <p className="text-sm text-gray-600 mt-2">Ready for download</p>
                  </div>
                </div>
              )}
            </div>

            {/* Details */}
            <div className="space-y-4">
              <div>
                <p className="text-sm text-gray-600 mb-1">Image ID</p>
                <p className="font-mono text-sm">{selectedImage.id}</p>
              </div>

              <div>
                <p className="text-sm text-gray-600 mb-1">Prompt Used</p>
                <p className="text-sm text-gray-700 leading-relaxed bg-gray-50 p-3 rounded">
                  {selectedImage.prompt_used}
                </p>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <p className="text-sm text-gray-600">Provider</p>
                  <p className="font-medium">{selectedImage.generation_provider}</p>
                </div>
                <div>
                  <p className="text-sm text-gray-600">Cost</p>
                  <p className="font-medium">${selectedImage.cost_usd}</p>
                </div>
              </div>

              {selectedImage.quality_score && (
                <div className="bg-blue-50 p-4 rounded-lg">
                  <p className="text-sm text-gray-600 mb-2">Quality Scores</p>
                  <div className="space-y-1 text-sm">
                    {selectedImage.quality_score && (
                      <p>Overall: <span className="font-medium">{selectedImage.quality_score}/10</span></p>
                    )}
                    {selectedImage.professional_appearance && (
                      <p>Professional: <span className="font-medium">{selectedImage.professional_appearance}/10</span></p>
                    )}
                    {selectedImage.conversion_potential && (
                      <p>Conversion: <span className="font-medium">{selectedImage.conversion_potential}/10</span></p>
                    )}
                  </div>
                </div>
              )}

              <button
                onClick={() => handleDownload(selectedImage)}
                disabled={isDownloading}
                className="w-full btn btn-primary hover:bg-blue-700 transition disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {isDownloading ? '⏳ Downloading...' : '⬇️ Download Image'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
