import { formatCount } from '../format';
import type { StoryData } from './storyData';

export interface Caption {
  title: string;
  text: string;
}

/**
 * The seven stages in plain words. The figures come from the data (the showcase file), so a caption never carries a number somebody typed;
 * before the data has arrived the captions say the same thing without the figures.
 */
export function captions(data: StoryData | null): Caption[] {
  const fields = data ? `This one product's record has ${formatCount(data.rawFields)} fields, and` : 'The record has many fields, and';
  const kept = data ? `${formatCount(data.silverColumns)} columns are kept` : 'only the columns that are needed are kept';
  const tables = data ? `This one product fills ${data.tableCount} of them` : 'One product fills several of them';
  const history = data
    ? `Some products have a long story. ${data.history.name} was edited ${data.history.versions} times, and its flags came and went. Each bar is one flag, from the day we first saw it to the day it ended.`
    : 'Some products have a long story. Their flags come and go as the product is edited: each bar is one flag, from the day we first saw it to the day it ended.';
  const checks = data
    ? `Every product is also checked against arithmetic rules. For ${data.checks.name}, ${data.checks.bad} of ${data.checks.rows.length} checks do not agree.`
    : 'Every product is also checked against arithmetic rules, and each check either agrees or does not.';
  return [
    { title: 'Open Food Facts publishes a file', text: 'Every morning Open Food Facts publishes a new file with every product that was added or changed.' },
    { title: 'We keep an untouched copy', text: `${fields} the usernames of the volunteers who edited it sit in some of them.` },
    { title: 'We clean it', text: `Usernames are scrambled into codes that never leave the private side, mistakes are caught, and ${kept}.` },
    { title: 'We build the tables', text: `From the clean copy we build the tables this site is drawn from. One barcode ties them together. ${tables}.` },
    { title: 'We keep every version', text: history },
    { title: 'We check the arithmetic', text: checks },
    { title: 'You see it', text: 'The tables become the charts, product cards and downloads on this site. Type a barcode and its card is there.' },
  ];
}
