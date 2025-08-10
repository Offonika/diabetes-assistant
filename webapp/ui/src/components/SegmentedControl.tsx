import { useId, useRef } from 'react';

export interface SegmentedItem {
  value: string;
  icon?: React.ReactNode;
  label?: string;
}

interface SegmentedControlProps {
  value: string;
  onChange: (value: string) => void;
  items: SegmentedItem[];
}

export const SegmentedControl = ({ value, onChange, items }: SegmentedControlProps) => {
  const groupId = useId();
  const itemRefs = useRef<HTMLLabelElement[]>([]);

  const handleKeyDown = (
    e: React.KeyboardEvent<HTMLLabelElement>,
    index: number,
  ) => {
    let newIndex = index;

    if (e.key === 'ArrowRight' || e.key === 'ArrowDown') {
      newIndex = (index + 1) % items.length;
    } else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') {
      newIndex = (index - 1 + items.length) % items.length;
    } else if (e.key === 'Home') {
      newIndex = 0;
    } else if (e.key === 'End') {
      newIndex = items.length - 1;
    } else {
      return;
    }

    e.preventDefault();
    itemRefs.current[newIndex]?.focus();
    onChange(items[newIndex].value);
  };

  return (
    <div className="segmented" role="radiogroup">
      {items.map((item, index) => {
        const id = `${groupId}-${index}`;
        return (
          <div className="segmented__item" key={item.value}>
            <input
              id={id}
              type="radio"
              name={groupId}
              checked={value === item.value}
              onChange={() => onChange(item.value)}
            />
            <label
              ref={(el) => (itemRefs.current[index] = el!)}
              htmlFor={id}
              role="radio"
              aria-checked={value === item.value}
              tabIndex={value === item.value ? 0 : -1}
              onKeyDown={(e) => handleKeyDown(e, index)}
            >
              {item.icon && (
                <span className="segmented__icon">{item.icon}</span>
              )}
              {item.label && (
                <span className="segmented__label">{item.label}</span>
              )}
            </label>
          </div>
        );
      })}
    </div>
  );
};
