"""
High-End Real Estate AI Video Generation System
Complete automation workflow using Google Veo and FFmpeg
"""

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path
import logging
from typing import List, Optional
from tqdm import tqdm

from veo_generator import VeoVideoGenerator
from video_composer import VideoComposer

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class PropertyVideoGenerator:
    """
    Manages the complete workflow for generating luxury property videos
    """

    # High-end real estate prompts (English)
    DEFAULT_PROMPTS = [
        # Exterior shot
        "Netflix production-style promotion video, luxurious modern apartment building exterior, "
        "cinematic camera moving towards the entrance, elegant facade with natural lighting, "
        "cool cinematic movement revealing architectural grandeur, no additional images",

        # Interior shot
        "Netflix production-style promotion video, spacious luxury apartment interior, "
        "cinematic camera moving towards the living space, elegant modern furnishings, "
        "natural light streaming through windows, cool sophisticated movement, no additional images",

        # Common areas
        "Netflix production-style promotion video, exclusive luxury building common areas, "
        "cinematic camera moving towards the elegant lobby entrance, premium architectural design, "
        "marble flooring with sophisticated lighting, cool cinematic movement, no additional images"
    ]

    def __init__(
        self,
        api_key: str,
        output_dir: str = "output",
        session_name: Optional[str] = None
    ):
        """
        Initialize the Property Video Generator

        Args:
            api_key: Google AI API key
            output_dir: Base output directory
            session_name: Optional session name (defaults to timestamp)
        """
        self.api_key = api_key
        self.veo_generator = VeoVideoGenerator(api_key)
        self.video_composer = VideoComposer()

        # Create session directory
        if session_name is None:
            session_name = datetime.now().strftime("%Y%m%d_%H%M%S")

        self.session_dir = Path(output_dir) / session_name
        self.session_dir.mkdir(parents=True, exist_ok=True)

        self.clips_dir = self.session_dir / "clips"
        self.clips_dir.mkdir(exist_ok=True)

        logger.info(f"Session directory: {self.session_dir}")

    def generate_video_clips(
        self,
        image_paths: List[str],
        prompts: Optional[List[str]] = None,
        duration: int = 8
    ) -> List[str]:
        """
        Generate video clips from images using Google Veo

        Args:
            image_paths: List of paths to input images (3 images expected)
            prompts: Optional list of prompts (uses defaults if not provided)
            duration: Duration of each clip in seconds

        Returns:
            List of paths to generated video clips
        """
        if len(image_paths) != 3:
            raise ValueError("Exactly 3 images are required (exterior, interior, common areas)")

        if prompts is None:
            prompts = self.DEFAULT_PROMPTS
        elif len(prompts) != len(image_paths):
            raise ValueError(f"Number of prompts ({len(prompts)}) must match number of images ({len(image_paths)})")

        # Verify all images exist
        for img_path in image_paths:
            if not os.path.exists(img_path):
                raise FileNotFoundError(f"Image not found: {img_path}")

        video_clips = []

        # Generate each clip with progress bar
        logger.info(f"Generating {len(image_paths)} video clips...")

        with tqdm(total=len(image_paths), desc="Generating clips", unit="clip") as pbar:
            for i, (image_path, prompt) in enumerate(zip(image_paths, prompts)):
                clip_name = f"clip_{i+1:02d}.mp4"
                output_path = self.clips_dir / clip_name

                logger.info(f"\n{'='*80}")
                logger.info(f"Clip {i+1}/{len(image_paths)}: {Path(image_path).name}")
                logger.info(f"{'='*80}")

                try:
                    video_path = self.veo_generator.generate_from_image_file(
                        image_path=image_path,
                        prompt=prompt,
                        output_path=str(output_path),
                        duration=duration
                    )
                    video_clips.append(video_path)
                    logger.info(f"✓ Clip {i+1} completed: {video_path}")

                except Exception as e:
                    logger.error(f"✗ Failed to generate clip {i+1}: {e}")
                    raise

                pbar.update(1)

        logger.info(f"\nAll {len(video_clips)} clips generated successfully!")
        return video_clips

    def compose_final_video(
        self,
        video_clips: List[str],
        output_name: str = "final_property_video.mp4",
        transition_type: str = "fade",
        transition_duration: float = 0.5,
        resolution: str = "1280x720"
    ) -> str:
        """
        Compose final video with transitions

        Args:
            video_clips: List of video clip paths
            output_name: Name of the output video file
            transition_type: Type of transition effect
            transition_duration: Duration of transitions in seconds
            resolution: Output video resolution

        Returns:
            Path to the final composed video
        """
        output_path = self.session_dir / output_name

        logger.info(f"\n{'='*80}")
        logger.info("Composing final video with transitions...")
        logger.info(f"{'='*80}")

        try:
            final_video = self.video_composer.compose_with_transitions(
                video_paths=video_clips,
                output_path=str(output_path),
                transition_type=transition_type,
                transition_duration=transition_duration,
                resolution=resolution
            )

            logger.info(f"✓ Final video created: {final_video}")
            return final_video

        except Exception as e:
            logger.error(f"✗ Failed to compose final video: {e}")
            raise

    def generate_complete_property_video(
        self,
        image_paths: List[str],
        output_name: str = "final_property_video.mp4",
        prompts: Optional[List[str]] = None,
        transition_type: str = "fade",
        transition_duration: float = 0.5,
        clip_duration: int = 8
    ) -> str:
        """
        Complete workflow: Generate clips and compose final video

        Args:
            image_paths: List of 3 image paths
            output_name: Name of output video file
            prompts: Optional custom prompts
            transition_type: Transition effect type
            transition_duration: Transition duration in seconds
            clip_duration: Duration of each clip in seconds

        Returns:
            Path to the final video
        """
        logger.info("="*80)
        logger.info("LUXURY PROPERTY VIDEO GENERATION WORKFLOW")
        logger.info("="*80)
        logger.info(f"Images: {len(image_paths)}")
        logger.info(f"Clip duration: {clip_duration}s each")
        logger.info(f"Transition: {transition_type} ({transition_duration}s)")
        logger.info(f"Expected total duration: ~{len(image_paths) * clip_duration - (len(image_paths) - 1) * transition_duration:.1f}s")
        logger.info("="*80)

        # Step 1: Generate video clips
        video_clips = self.generate_video_clips(
            image_paths=image_paths,
            prompts=prompts,
            duration=clip_duration
        )

        # Step 2: Compose final video
        final_video = self.compose_final_video(
            video_clips=video_clips,
            output_name=output_name,
            transition_type=transition_type,
            transition_duration=transition_duration
        )

        logger.info("\n" + "="*80)
        logger.info("✓ WORKFLOW COMPLETED SUCCESSFULLY!")
        logger.info("="*80)
        logger.info(f"Final video: {final_video}")
        logger.info(f"Session directory: {self.session_dir}")
        logger.info("="*80)

        return final_video


def main():
    """
    CLI entry point
    """
    parser = argparse.ArgumentParser(
        description="High-End Real Estate AI Video Generation System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic usage with 3 property images
  python generate_property_video.py \\
    --api-key YOUR_GOOGLE_API_KEY \\
    --images exterior.jpg interior.jpg lobby.jpg \\
    --output luxury_apartment.mp4

  # Custom transition and output directory
  python generate_property_video.py \\
    --api-key YOUR_GOOGLE_API_KEY \\
    --images photo1.jpg photo2.jpg photo3.jpg \\
    --transition wipeleft \\
    --transition-duration 0.8 \\
    --output-dir /path/to/output \\
    --output final_video.mp4

  # Using environment variable for API key
  export GOOGLE_API_KEY=your_api_key_here
  python generate_property_video.py \\
    --images img1.jpg img2.jpg img3.jpg
        """
    )

    parser.add_argument(
        "--api-key",
        type=str,
        help="Google AI API key (or set GOOGLE_API_KEY environment variable)"
    )

    parser.add_argument(
        "--images",
        type=str,
        nargs=3,
        required=True,
        metavar=("EXTERIOR", "INTERIOR", "COMMON_AREA"),
        help="Paths to 3 property images (exterior, interior, common areas)"
    )

    parser.add_argument(
        "--output",
        type=str,
        default="final_property_video.mp4",
        help="Output video filename (default: final_property_video.mp4)"
    )

    parser.add_argument(
        "--output-dir",
        type=str,
        default="output",
        help="Base output directory (default: output/)"
    )

    parser.add_argument(
        "--session-name",
        type=str,
        help="Session name (default: timestamp)"
    )

    parser.add_argument(
        "--transition",
        type=str,
        default="fade",
        choices=["fade", "wipeleft", "wiperight", "wipeup", "wipedown", "slideleft", "slideright"],
        help="Transition type (default: fade)"
    )

    parser.add_argument(
        "--transition-duration",
        type=float,
        default=0.5,
        help="Transition duration in seconds (default: 0.5)"
    )

    parser.add_argument(
        "--clip-duration",
        type=int,
        default=8,
        help="Duration of each clip in seconds (default: 8)"
    )

    parser.add_argument(
        "--resolution",
        type=str,
        default="1280x720",
        help="Output resolution (default: 1280x720)"
    )

    parser.add_argument(
        "--prompts",
        type=str,
        nargs=3,
        metavar=("PROMPT1", "PROMPT2", "PROMPT3"),
        help="Custom prompts for each video clip (optional)"
    )

    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging"
    )

    args = parser.parse_args()

    # Set logging level
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Get API key
    api_key = args.api_key or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        logger.error("Error: API key not provided. Use --api-key or set GOOGLE_API_KEY environment variable.")
        sys.exit(1)

    try:
        # Initialize generator
        generator = PropertyVideoGenerator(
            api_key=api_key,
            output_dir=args.output_dir,
            session_name=args.session_name
        )

        # Generate complete video
        final_video = generator.generate_complete_property_video(
            image_paths=args.images,
            output_name=args.output,
            prompts=args.prompts,
            transition_type=args.transition,
            transition_duration=args.transition_duration,
            clip_duration=args.clip_duration
        )

        print("\n" + "="*80)
        print("SUCCESS! Your luxury property video is ready!")
        print("="*80)
        print(f"📹 Final video: {final_video}")
        print(f"📁 Session folder: {generator.session_dir}")
        print("="*80)

    except KeyboardInterrupt:
        logger.warning("\n\nOperation cancelled by user")
        sys.exit(130)

    except Exception as e:
        logger.error(f"\n\n✗ Error: {e}", exc_info=args.verbose)
        sys.exit(1)


if __name__ == "__main__":
    main()
