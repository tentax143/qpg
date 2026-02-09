'use client';

export default function Table({
  columns = [],
  data = [],
  onRowClick,
  selectable = false,
  selectedRows = new Set(),
  onSelectRow,
  onSelectAll,
}) {
  const isAllSelected = data.length > 0 && selectedRows.size === data.length;

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-gray-200 bg-white">
            {selectable && (
              <th className="px-4 py-3 text-left w-12">
                <input
                  type="checkbox"
                  checked={isAllSelected}
                  onChange={() => onSelectAll && onSelectAll(!isAllSelected)}
                  className="rounded border-gray-300 cursor-pointer"
                />
              </th>
            )}
            {columns.map((col) => (
              <th
                key={col.key}
                className={`px-4 py-3 text-left font-semibold text-gray-900 ${
                  col.width ? `w-${col.width}` : ''
                }`}
              >
                {col.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.map((row, rowIdx) => (
            <tr
              key={rowIdx}
              onClick={() => onRowClick && onRowClick(row)}
              className={`border-b border-gray-100 ${
                onRowClick ? 'cursor-pointer hover:bg-gray-50' : ''
              } transition-colors`}
            >
              {selectable && (
                <td className="px-4 py-3">
                  <input
                    type="checkbox"
                    checked={selectedRows.has(row.id)}
                    onChange={() => onSelectRow && onSelectRow(row.id)}
                    onClick={(e) => e.stopPropagation()}
                    className="rounded border-gray-300 cursor-pointer"
                  />
                </td>
              )}
              {columns.map((col) => (
                <td key={`${rowIdx}-${col.key}`} className="px-4 py-3">
                  {col.render ? col.render(row[col.key], row) : row[col.key]}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {data.length === 0 && (
        <div className="text-center py-12 text-gray-500">
          <p>No data available</p>
        </div>
      )}
    </div>
  );
}
