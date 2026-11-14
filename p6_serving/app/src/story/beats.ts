import { formatCount } from '../format';
import type { StoryData } from './storyData';

export interface Caption {
  title: string;
  text: string;
}

/**
 * The five stages in plain words. The figures come from the data (the showcase file), so a caption never carries a number somebody typed;
 * before the data has arrived the captions say the same thing without the figures.
 */
export function captions(data: StoryData | null): Caption[] {
  const fields = data ? `This one product's record has ${formatCount(data.rawFields)} fields, and` : 'The record has many fields, and';
  const kept = data ? `${formatCount(data.silverColumns)} columns are kept` : 'only the columns that are needed are kept';
  const tables = data ? `This one product fills ${data.tableCount} of them` : 'One product fills several of them';
  return [
    { title: 'Open Food Facts publishes a file', text: 'Every morning Open Food Facts publishes a new file with every product that was added or changed.' },
    { title: 'We keep an untouched copy', text: `${fields} the usernames of the volunteers who edited it sit in some of them.` },
    { title: 'We clean it', text: `Usernames are scrambled into codes that never leave the private side, mistakes are caught, and ${kept}.` },
    { title: 'We build the tables', text: `From the clean copy we build the tables this site is drawn from: history, flags, nutrition and more. ${tables}.` },
    { title: 'You see it', text: 'The tables become the charts, product cards and downloads on this site. The page carries on below.' },
  ];
}
