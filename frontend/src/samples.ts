// The repository's sample files, bundled so the live demo can be tried without any data.
import farmSurvey from "../../samples/farm_survey.kml?url";
import parcels from "../../samples/parcels_wgs84.zip?url";
import pipelines from "../../samples/pipelines_utm43n.zip?url";

export interface Sample {
  label: string;
  detail: string;
  url: string;
  filename: string;
}

export const SAMPLES: Sample[] = [
  {
    label: "Farm survey",
    detail: "KML · plots, roads, a well and a 3D model",
    url: farmSurvey,
    filename: "farm_survey.kml",
  },
  {
    label: "Land parcels",
    detail: "Shapefile · WGS 84 polygons",
    url: parcels,
    filename: "parcels_wgs84.zip",
  },
  {
    label: "Pipelines",
    detail: "Shapefile · UTM 43N lines (metres)",
    url: pipelines,
    filename: "pipelines_utm43n.zip",
  },
];

export async function loadSample(sample: Sample): Promise<File> {
  const response = await fetch(sample.url);
  return new File([await response.blob()], sample.filename);
}
