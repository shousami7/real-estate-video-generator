import img1 from '@assets/generated_images/cinematic_portrait_of_a_woman_with_neon_lighting.png';
import img2 from '@assets/generated_images/futuristic_tokyo_street_at_night.png';
import img3 from '@assets/generated_images/macro_shot_of_mechanical_gears.png';
import img4 from '@assets/generated_images/abstract_data_visualization.png';

export interface Frame {
  id: string;
  src: string;
  timecode: string;
}

const baseFrames = [
  { src: img1, id: 'frame-1' },
  { src: img2, id: 'frame-2' },
  { src: img3, id: 'frame-3' },
  { src: img4, id: 'frame-4' },
];

// Generate a sequence to simulate video
export const mockFrames: Frame[] = Array.from({ length: 24 }).map((_, i) => {
  const base = baseFrames[i % baseFrames.length];
  const seconds = Math.floor(i / 24);
  const frames = i % 24;
  return {
    id: `${base.id}-${i}`,
    src: base.src,
    timecode: `00:00:${seconds.toString().padStart(2, '0')}:${frames.toString().padStart(2, '0')}`
  };
});
