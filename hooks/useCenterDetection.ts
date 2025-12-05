import { useEffect, useState } from "react";

interface UseCenterDetectionOptions {
  scrollX: number;
  viewportWidth: number;
  itemSize: number;
  gap?: number;
  totalCount: number;
}

export function useCenterDetection({
  scrollX,
  viewportWidth,
  itemSize,
  gap = 0,
  totalCount,
}: UseCenterDetectionOptions) {
  const [centerIndex, setCenterIndex] = useState(0);

  useEffect(() => {
    const spacing = itemSize + gap;
    if (spacing <= 0) return;
    const centerPosition = scrollX + viewportWidth / 2;
    const index = Math.round(centerPosition / spacing);
    setCenterIndex(Math.min(Math.max(index, 0), totalCount - 1));
  }, [gap, itemSize, scrollX, totalCount, viewportWidth]);

  return centerIndex;
}

export default useCenterDetection;
